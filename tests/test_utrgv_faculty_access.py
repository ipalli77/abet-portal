from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from werkzeug.security import generate_password_hash

from abet_platform import create_app
from abet_platform.db import get_db


OWNER_EMAIL = "isaac.palli@utrgv.edu"

EXPECTED_FACULTY = {
    "Yingchen Yang": ("yingchen.yang@utrgv.edu", ("MECE 1101",)),
    "Lawrence Cano": ("lawrence.cano@utrgv.edu", ("MECE 1221",)),
    "Misael Martinez": (
        "misael.e.martinez01@utrgv.edu",
        ("MECE 2140",),
    ),
    "Eleazar Marquez": (
        "eleazar.marquez01@utrgv.edu",
        ("MECE 2302", "MECE 4362"),
    ),
    "Robert Jones": ("robert.jones@utrgv.edu", ("MECE 2340",)),
    "Jose Sanchez": (
        "jose.j.sanchez01@utrgv.edu",
        ("MECE 3170", "MECE 3336"),
    ),
    "Nadim Zgheib": ("nadim.zgheib@utrgv.edu", ("MECE 3315",)),
    "Constantine Tarawneh": (
        "constantine.tarawneh@utrgv.edu",
        ("MECE 3360",),
    ),
    "Robert Freeman": ("robert.freeman@utrgv.edu", ("MECE 3380",)),
    "Dumitru Caruntu": ("dumitru.caruntu@utrgv.edu", ("MECE 3450",)),
    "Javier Ortega": ("javier.ortega@utrgv.edu", ("MECE 4350",)),
    "Noe Vargas": ("noe.vargas@utrgv.edu", ("MECE 4361",)),
    "Mataz Alcoutlabi": ("mataz.alcoutlabi@utrgv.edu", ("PHIL 2393",)),
}


class UtrgvFacultyAccessTests(unittest.TestCase):
    """Customer-specific identity, allowlist, and course-scope contracts."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.config = {
            "TESTING": True,
            "SECRET_KEY": "utrgv-faculty-access-secret",
            "DATABASE": str(root / "utrgv.db"),
            "UPLOAD_FOLDER": str(root / "uploads"),
            "EDITION": "utrgv_mece",
            "PRODUCT_NAME": "UTRGV ME Accreditation Hub",
            "CUSTOMER_NAME": "UTRGV Department of Mechanical Engineering",
        }
        self.app = create_app(self.config)
        self.client = self.app.test_client()
        self._setup_and_login_owner()
        with self.app.app_context():
            db = get_db()
            program = db.execute(
                "SELECT * FROM programs WHERE code='BSME'"
            ).fetchone()
            owner = db.execute(
                "SELECT * FROM users WHERE email=?", (OWNER_EMAIL,)
            ).fetchone()
            self.ids = {
                "organization": program["organization_id"],
                "program": program["id"],
                "owner": owner["id"],
                "courses": {
                    row["code"]: row["id"]
                    for row in db.execute(
                        "SELECT id,code FROM courses WHERE program_id=?",
                        (program["id"],),
                    )
                },
            }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def csrf(self) -> str:
        with self.client.session_transaction() as session:
            return session["csrf_token"]

    def as_user(self, user_id: int) -> None:
        with self.client.session_transaction() as session:
            session.clear()
            session["user_id"] = user_id
            session["organization_id"] = self.ids["organization"]
            session["program_id"] = self.ids["program"]
            session["csrf_token"] = "utrgv-faculty-access-csrf"

    def _setup_and_login_owner(self) -> None:
        self.client.get("/setup")
        rejected = self.client.post(
            "/setup",
            data={
                "csrf_token": self.csrf(),
                "full_name": "Unauthorized Initializer",
                "email": "another.person@utrgv.edu",
                "password": "owner-password-long",
            },
        )
        self.assertEqual(rejected.status_code, 200)
        with self.app.app_context():
            self.assertEqual(
                get_db().execute("SELECT COUNT(*) FROM users").fetchone()[0], 0
            )

        created = self.client.post(
            "/setup",
            data={
                "csrf_token": self.csrf(),
                "full_name": "Isaac Choutapalli",
                "email": OWNER_EMAIL.upper(),
                "password": "owner-password-long",
            },
        )
        self.assertEqual(created.status_code, 302)
        self.client.get("/login")
        logged_in = self.client.post(
            "/login",
            data={
                "csrf_token": self.csrf(),
                "login": OWNER_EMAIL,
                "password": "owner-password-long",
            },
        )
        self.assertEqual(logged_in.status_code, 302)

    def _roster_id(self, display_name: str) -> int:
        with self.app.app_context():
            return get_db().execute(
                "SELECT id FROM faculty_roster WHERE program_id=? AND display_name=?",
                (self.ids["program"], display_name),
            ).fetchone()[0]

    def _activate(self, display_name: str, *, actor_id: int | None = None) -> int:
        if actor_id is not None:
            self.as_user(actor_id)
        roster_id = self._roster_id(display_name)
        response = self.client.post(
            f"/utrgv/faculty/{roster_id}/activate",
            data={
                "csrf_token": self.csrf(),
                "username": display_name,
                "temporary_password": "temporary-password",
                # These forged fields must never override the invitation.
                "email": "forged.address@utrgv.edu",
                "role": "admin",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            return get_db().execute(
                "SELECT user_id FROM faculty_roster WHERE id=?", (roster_id,)
            ).fetchone()[0]

    def _assessment_payload(
        self,
        course_code: str,
        *,
        tool: str,
        record_version: int | None = None,
        admin_note: str | None = None,
    ) -> dict[str, str | int]:
        with self.app.app_context():
            db = get_db()
            outcome = db.execute(
                "SELECT id FROM outcomes WHERE program_id=? AND code='SLO1'",
                (self.ids["program"],),
            ).fetchone()
            payload: dict[str, str | int] = {
                "csrf_token": self.csrf(),
                "term_id": db.execute(
                    """SELECT id FROM academic_terms WHERE program_id=?
                       ORDER BY sort_order DESC,id DESC LIMIT 1""",
                    (self.ids["program"],),
                ).fetchone()[0],
                "course_id": self.ids["courses"][course_code],
                "outcome_id": outcome["id"],
                "indicator_id": db.execute(
                    """SELECT id FROM performance_indicators
                       WHERE outcome_id=? AND is_active=1
                       ORDER BY display_order,id LIMIT 1""",
                    (outcome["id"],),
                ).fetchone()[0],
                "rubric_id": db.execute(
                    """SELECT id FROM rubrics WHERE program_id=?
                       ORDER BY is_default DESC,id LIMIT 1""",
                    (self.ids["program"],),
                ).fetchone()[0],
                "campus": "Edinburg",
                "method": "direct",
                "assessment_tool": tool,
                "bloom_level": "Analyze",
                "target": "70",
                "expert_percent": "30",
                "practitioner_percent": "50",
                "apprentice_percent": "10",
                "novice_percent": "10",
                "rationale": "Directly aligned to the selected performance indicator.",
                "observations": "Students demonstrated the expected analytical skill.",
                "action_notes": "Retain the activity and review it next term.",
            }
        if record_version is not None:
            payload["record_version"] = record_version
        if admin_note is not None:
            payload["admin_change_note"] = admin_note
        return payload

    def test_exact_roster_emails_courses_and_owner_scope(self) -> None:
        with self.app.app_context():
            db = get_db()
            actual = {}
            for row in db.execute(
                """SELECT id,legacy_name,display_name,approved_email,status,user_id
                     FROM faculty_roster WHERE program_id=? ORDER BY display_name""",
                (self.ids["program"],),
            ):
                courses = tuple(
                    course["code"]
                    for course in db.execute(
                        """SELECT c.code FROM faculty_roster_courses frc
                           JOIN courses c ON c.id=frc.course_id
                           WHERE frc.faculty_roster_id=? ORDER BY c.code""",
                        (row["id"],),
                    )
                )
                actual[row["display_name"]] = (row["approved_email"], courses)
                self.assertEqual(row["legacy_name"], row["display_name"])
                self.assertEqual(row["status"], "pending")
                self.assertIsNone(row["user_id"])

            self.assertEqual(actual, EXPECTED_FACULTY)
            self.assertEqual(len(actual), 13)
            self.assertEqual(sum(len(courses) for _email, courses in actual.values()), 15)
            self.assertFalse(
                db.execute(
                    """SELECT 1 FROM faculty_roster
                       WHERE program_id=? AND legacy_name IN
                             ('Constantine T','Caruntu D','Isaac Choutapalli','Kamal Sarkar')""",
                    (self.ids["program"],),
                ).fetchone()
            )

            owner = db.execute(
                """SELECT u.email,m.role,pm.access_level
                   FROM users u
                   JOIN memberships m ON m.user_id=u.id
                   JOIN program_members pm ON pm.user_id=u.id
                   WHERE u.id=? AND m.organization_id=? AND pm.program_id=?""",
                (
                    self.ids["owner"],
                    self.ids["organization"],
                    self.ids["program"],
                ),
            ).fetchone()
            self.assertEqual(owner["email"], OWNER_EMAIL)
            self.assertEqual(owner["role"], "owner")
            self.assertEqual(owner["access_level"], "manager")
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM course_assignments WHERE user_id=?",
                    (self.ids["owner"],),
                ).fetchone()[0],
                0,
            )

        # Owner/manager access is unrestricted even without course assignments.
        page = self.client.get("/assessments/new")
        self.assertEqual(page.status_code, 200)
        for course_code in self.ids["courses"]:
            self.assertIn(course_code.encode(), page.data)
        self.assertEqual(self.client.get("/users").status_code, 200)
        self.assertEqual(self.client.get("/utrgv/faculty").status_code, 200)
        self.assertEqual(self.client.get("/audit").status_code, 200)

    def test_users_page_shows_every_invitation_and_no_duplicate_active_faculty(
        self,
    ) -> None:
        page = self.client.get("/users")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"All courses (unrestricted)", page.data)
        faculty_rows = re.findall(
            rb'<tr class="roster-faculty-row">(.*?)</tr>',
            page.data,
            flags=re.DOTALL,
        )
        self.assertEqual(len(faculty_rows), len(EXPECTED_FACULTY))
        for display_name, (email, course_codes) in EXPECTED_FACULTY.items():
            matching_rows = [row for row in faculty_rows if email.encode() in row]
            self.assertEqual(len(matching_rows), 1, display_name)
            row = matching_rows[0]
            self.assertIn(display_name.encode(), row)
            for course_code in course_codes:
                self.assertIn(course_code.encode(), row)
            self.assertIn(b"Pending activation", row)
            self.assertIn(b"Cannot sign in until activated.", row)
            self.assertIn(b"Activate in faculty roster", row)

        faculty_id = self._activate("Nadim Zgheib")
        page = self.client.get("/users")
        self.assertEqual(page.status_code, 200)
        # The activated account is represented by its approved faculty row, not
        # repeated a second time as a general user account.
        self.assertEqual(page.data.count(b"nadim.zgheib@utrgv.edu"), 1)
        nadim_row = next(
            row
            for row in re.findall(
                rb'<tr class="roster-faculty-row">(.*?)</tr>',
                page.data,
                flags=re.DOTALL,
            )
            if b"nadim.zgheib@utrgv.edu" in row
        )
        self.assertIn(b">Active</span>", nadim_row)
        self.assertIn(b"MECE 3315", nadim_row)
        self.assertIn(b"Manage approved access", nadim_row)

        with self.app.app_context():
            db = get_db()
            db.execute("UPDATE users SET is_active=0 WHERE id=?", (faculty_id,))
            db.execute(
                "UPDATE faculty_roster SET status='inactive' WHERE user_id=?",
                (faculty_id,),
            )
            db.commit()
        page = self.client.get("/users")
        nadim_row = next(
            row
            for row in re.findall(
                rb'<tr class="roster-faculty-row">(.*?)</tr>',
                page.data,
                flags=re.DOTALL,
            )
            if b"nadim.zgheib@utrgv.edu" in row
        )
        self.assertIn(b">Inactive</span>", nadim_row)
        self.assertIn(b"Sign-in is disabled.", nadim_row)

    def test_faculty_cannot_self_register_or_bypass_the_allowlist(self) -> None:
        for path in ("/signup", "/register"):
            self.assertEqual(self.client.get(path).status_code, 404)
            self.assertEqual(
                self.client.post(path, data={"csrf_token": self.csrf()}).status_code,
                404,
            )

        for email in ("unknown.faculty@utrgv.edu", "nadim.zgheib@utrgv.edu"):
            denied = self.client.post(
                "/users",
                data={
                    "csrf_token": self.csrf(),
                    "full_name": "Unapproved Faculty",
                    "email": email,
                    "role": "faculty",
                    "temporary_password": "temporary-password",
                },
            )
            self.assertEqual(denied.status_code, 403)

        with self.app.app_context():
            db = get_db()
            self.assertFalse(
                db.execute(
                    "SELECT 1 FROM users WHERE email IN (?,?)",
                    ("unknown.faculty@utrgv.edu", "nadim.zgheib@utrgv.edu"),
                ).fetchone()
            )
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM faculty_roster WHERE program_id=?",
                    (self.ids["program"],),
                ).fetchone()[0],
                13,
            )

    def test_login_requires_an_active_matching_invitation_and_owner_can_repair_it(self) -> None:
        with self.app.app_context():
            db = get_db()
            unlinked_id = db.execute(
                """INSERT INTO users(email,full_name,password_hash)
                   VALUES (?,?,?)""",
                (
                    "manually.created@utrgv.edu",
                    "Manually Created Faculty",
                    generate_password_hash("manual-password-long"),
                ),
            ).lastrowid
            db.execute(
                """INSERT INTO memberships(user_id,organization_id,role)
                   VALUES (?,?,'faculty')""",
                (unlinked_id, self.ids["organization"]),
            )
            db.execute(
                """INSERT INTO program_members(program_id,user_id,access_level)
                   VALUES (?,?,'editor')""",
                (self.ids["program"], unlinked_id),
            )
            db.commit()

        self.client.post("/logout", data={"csrf_token": self.csrf()})
        self.client.get("/login")
        denied = self.client.post(
            "/login",
            data={
                "csrf_token": self.csrf(),
                "login": "manually.created@utrgv.edu",
                "password": "manual-password-long",
            },
        )
        self.assertEqual(denied.status_code, 200)
        self.assertIn(b"Email or password was not recognized", denied.data)
        with self.client.session_transaction() as session:
            self.assertNotIn("user_id", session)

        faculty_id = self._activate("Nadim Zgheib", actor_id=self.ids["owner"])
        with self.app.app_context():
            db = get_db()
            db.execute(
                """UPDATE users
                   SET email='mismatched.address@utrgv.edu',must_change_password=0
                   WHERE id=?""",
                (faculty_id,),
            )
            db.commit()

        self.client.post("/logout", data={"csrf_token": self.csrf()})
        self.client.get("/login")
        mismatched = self.client.post(
            "/login",
            data={
                "csrf_token": self.csrf(),
                "login": "mismatched.address@utrgv.edu",
                "password": "temporary-password",
            },
        )
        self.assertEqual(mismatched.status_code, 200)
        self.assertIn(b"Email or password was not recognized", mismatched.data)
        with self.client.session_transaction() as session:
            self.assertNotIn("user_id", session)

        # The owner repairs both the approved identity and linked account in one
        # audited roster update. No direct /users faculty edit is needed.
        self.as_user(self.ids["owner"])
        roster_id = self._roster_id("Nadim Zgheib")
        repaired = self.client.post(
            f"/utrgv/faculty/{roster_id}/invitation",
            data={
                "csrf_token": self.csrf(),
                "display_name": "Nadim Zgheib",
                "approved_email": "nadim.zgheib@utrgv.edu",
                "course_ids": [self.ids["courses"]["MECE 3315"]],
            },
        )
        self.assertEqual(repaired.status_code, 302)

        self.client.post("/logout", data={"csrf_token": self.csrf()})
        self.client.get("/login")
        restored = self.client.post(
            "/login",
            data={
                "csrf_token": self.csrf(),
                "login": "nadim.zgheib@utrgv.edu",
                "password": "temporary-password",
            },
        )
        self.assertEqual(restored.status_code, 302)
        self.assertEqual(restored.headers["Location"], "/")

    def test_owner_can_add_and_change_an_invitation_and_reseed_preserves_it(self) -> None:
        added = self.client.post(
            "/utrgv/faculty/invitations",
            data={
                "csrf_token": self.csrf(),
                "display_name": "Additional Faculty",
                "approved_email": "additional.faculty@utrgv.edu",
                "course_ids": [
                    self.ids["courses"]["MECE 1101"],
                    self.ids["courses"]["MECE 1221"],
                ],
            },
        )
        self.assertEqual(added.status_code, 302)
        with self.app.app_context():
            db = get_db()
            roster = db.execute(
                """SELECT * FROM faculty_roster
                   WHERE program_id=? AND approved_email=?""",
                (self.ids["program"], "additional.faculty@utrgv.edu"),
            ).fetchone()
            self.assertIsNotNone(roster)
            self.assertEqual(roster["status"], "pending")
            self.assertIsNone(roster["user_id"])
            roster_id = roster["id"]

        changed = self.client.post(
            f"/utrgv/faculty/{roster_id}/invitation",
            data={
                "csrf_token": self.csrf(),
                "display_name": "Additional Faculty Member",
                "approved_email": "changed.faculty@utrgv.edu",
                "course_ids": [self.ids["courses"]["MECE 2140"]],
            },
        )
        self.assertEqual(changed.status_code, 302)

        with self.app.app_context():
            db = get_db()
            before_seed = db.execute(
                "SELECT * FROM faculty_roster WHERE id=?", (roster_id,)
            ).fetchone()
            before_courses = tuple(
                row["course_id"]
                for row in db.execute(
                    """SELECT course_id FROM faculty_roster_courses
                       WHERE faculty_roster_id=? ORDER BY course_id""",
                    (roster_id,),
                )
            )
            from abet_platform.utrgv_config import seed_utrgv_faculty_roster

            with db:
                seed_utrgv_faculty_roster(db, self.ids["program"])
                seed_utrgv_faculty_roster(db, self.ids["program"])
            after_seed = db.execute(
                "SELECT * FROM faculty_roster WHERE id=?", (roster_id,)
            ).fetchone()
            after_courses = tuple(
                row["course_id"]
                for row in db.execute(
                    """SELECT course_id FROM faculty_roster_courses
                       WHERE faculty_roster_id=? ORDER BY course_id""",
                    (roster_id,),
                )
            )
            self.assertEqual(after_seed["display_name"], "Additional Faculty Member")
            self.assertEqual(after_seed["approved_email"], "changed.faculty@utrgv.edu")
            self.assertEqual(after_seed["status"], before_seed["status"])
            self.assertEqual(after_courses, before_courses)
            self.assertEqual(after_courses, (self.ids["courses"]["MECE 2140"],))

            events = db.execute(
                """SELECT action,details_json FROM audit_events
                   WHERE entity_type='faculty_roster' AND entity_id=?
                   ORDER BY id""",
                (str(roster_id),),
            ).fetchall()
            self.assertEqual([event["action"] for event in events], ["invite", "update_invitation"])
            self.assertTrue(all(json.loads(event["details_json"])["owner_approved"] for event in events))

    def test_admin_can_activate_but_cannot_change_the_allowlist(self) -> None:
        created = self.client.post(
            "/users",
            data={
                "csrf_token": self.csrf(),
                "full_name": "ABET Administrator",
                "email": "abet.admin@utrgv.edu",
                "role": "admin",
                "temporary_password": "temporary-password",
            },
        )
        self.assertEqual(created.status_code, 302)
        with self.app.app_context():
            db = get_db()
            admin_id = db.execute(
                "SELECT id FROM users WHERE email='abet.admin@utrgv.edu'"
            ).fetchone()[0]
            db.execute(
                "UPDATE users SET must_change_password=0 WHERE id=?", (admin_id,)
            )
            db.commit()

        self.as_user(admin_id)
        roster_id = self._roster_id("Nadim Zgheib")
        denied_add = self.client.post(
            "/utrgv/faculty/invitations",
            data={
                "csrf_token": self.csrf(),
                "display_name": "Unapproved Addition",
                "approved_email": "unapproved.addition@utrgv.edu",
                "course_ids": [self.ids["courses"]["MECE 3315"]],
            },
        )
        self.assertEqual(denied_add.status_code, 403)
        denied_change = self.client.post(
            f"/utrgv/faculty/{roster_id}/invitation",
            data={
                "csrf_token": self.csrf(),
                "display_name": "Changed By Admin",
                "approved_email": "changed.by.admin@utrgv.edu",
                "course_ids": [self.ids["courses"]["MECE 2340"]],
            },
        )
        self.assertEqual(denied_change.status_code, 403)
        page = self.client.get("/utrgv/faculty")
        self.assertEqual(page.status_code, 200)
        self.assertNotIn(b"Add approved faculty", page.data)
        self.assertNotIn(b"Edit approved invitation", page.data)

        user_id = self._activate("Nadim Zgheib", actor_id=admin_id)
        with self.app.app_context():
            db = get_db()
            account = db.execute(
                """SELECT u.email,u.full_name,u.must_change_password,m.role,
                          pm.access_level
                   FROM users u
                   JOIN memberships m ON m.user_id=u.id
                   JOIN program_members pm ON pm.user_id=u.id
                   WHERE u.id=? AND m.organization_id=? AND pm.program_id=?""",
                (user_id, self.ids["organization"], self.ids["program"]),
            ).fetchone()
            self.assertEqual(account["email"], "nadim.zgheib@utrgv.edu")
            self.assertEqual(account["full_name"], "Nadim Zgheib")
            self.assertEqual(account["role"], "faculty")
            self.assertEqual(account["access_level"], "editor")
            self.assertEqual(account["must_change_password"], 1)
            assigned = [
                row["code"]
                for row in db.execute(
                    """SELECT c.code FROM course_assignments ca
                       JOIN courses c ON c.id=ca.course_id
                       WHERE ca.user_id=? ORDER BY c.code""",
                    (user_id,),
                )
            ]
            self.assertEqual(assigned, ["MECE 3315"])
            activation = db.execute(
                """SELECT details_json FROM audit_events
                   WHERE action='activate' AND entity_type='faculty_roster'
                     AND entity_id=? ORDER BY id DESC LIMIT 1""",
                (str(roster_id),),
            ).fetchone()
            details = json.loads(activation["details_json"])
            self.assertEqual(details["approved_email"], "nadim.zgheib@utrgv.edu")
            self.assertEqual(details["role"], "faculty")

    def test_owner_update_syncs_active_access_without_rewriting_provenance(self) -> None:
        faculty_id = self._activate("Nadim Zgheib")
        with self.app.app_context():
            db = get_db()
            db.execute(
                "UPDATE users SET must_change_password=0 WHERE id=?", (faculty_id,)
            )
            db.commit()

        self.as_user(faculty_id)
        created = self.client.post(
            "/assessments/new",
            data=self._assessment_payload(
                "MECE 3315", tool="Faculty provenance assessment"
            ),
        )
        self.assertEqual(created.status_code, 302)
        with self.app.app_context():
            db = get_db()
            record = db.execute(
                """SELECT id,collected_by,course_id,record_version
                   FROM assessment_records WHERE assessment_tool=?""",
                ("Faculty provenance assessment",),
            ).fetchone()
            original = dict(record)

        self.as_user(self.ids["owner"])
        roster_id = self._roster_id("Nadim Zgheib")
        updated = self.client.post(
            f"/utrgv/faculty/{roster_id}/invitation",
            data={
                "csrf_token": self.csrf(),
                "display_name": "Nadim Zgheib",
                "approved_email": "nadim.updated@utrgv.edu",
                "course_ids": [self.ids["courses"]["MECE 2340"]],
            },
        )
        self.assertEqual(updated.status_code, 302)

        with self.app.app_context():
            db = get_db()
            unchanged = db.execute(
                """SELECT collected_by,course_id,record_version
                   FROM assessment_records WHERE id=?""",
                (original["id"],),
            ).fetchone()
            self.assertEqual(unchanged["collected_by"], original["collected_by"])
            self.assertEqual(unchanged["course_id"], original["course_id"])
            self.assertEqual(unchanged["record_version"], original["record_version"])
            account = db.execute(
                "SELECT email FROM users WHERE id=?", (faculty_id,)
            ).fetchone()
            self.assertEqual(account["email"], "nadim.updated@utrgv.edu")
            assigned = db.execute(
                """SELECT c.code FROM course_assignments ca
                   JOIN courses c ON c.id=ca.course_id WHERE ca.user_id=?""",
                (faculty_id,),
            ).fetchall()
            self.assertEqual([row["code"] for row in assigned], ["MECE 2340"])

        # The owner may still edit the faculty-created record regardless of the
        # faculty member's newly narrowed course scope.
        owner_edit = self.client.post(
            f"/assessments/{original['id']}/edit",
            data=self._assessment_payload(
                "MECE 4362",
                tool="Owner-corrected assessment",
                record_version=original["record_version"],
                admin_note="Owner corrected the course association.",
            ),
        )
        self.assertEqual(owner_edit.status_code, 302)
        with self.app.app_context():
            db = get_db()
            corrected = db.execute(
                """SELECT collected_by,course_id,assessment_tool
                   FROM assessment_records WHERE id=?""",
                (original["id"],),
            ).fetchone()
            self.assertEqual(corrected["collected_by"], faculty_id)
            self.assertEqual(corrected["course_id"], self.ids["courses"]["MECE 4362"])
            self.assertEqual(corrected["assessment_tool"], "Owner-corrected assessment")
            revision = db.execute(
                """SELECT changed_by,change_note FROM assessment_revisions
                   WHERE assessment_id=? ORDER BY id DESC LIMIT 1""",
                (original["id"],),
            ).fetchone()
            self.assertEqual(revision["changed_by"], self.ids["owner"])
            self.assertEqual(
                revision["change_note"], "Owner corrected the course association."
            )

    def test_existing_database_migration_is_idempotent_and_program_scoped(self) -> None:
        with self.app.app_context():
            db = get_db()
            alias_ids = {}
            for canonical, alias in (
                ("Constantine Tarawneh", "Constantine T"),
                ("Dumitru Caruntu", "Caruntu D"),
            ):
                row = db.execute(
                    """SELECT id FROM faculty_roster
                       WHERE program_id=? AND legacy_name=?""",
                    (self.ids["program"], canonical),
                ).fetchone()
                alias_ids[canonical] = row["id"]
                db.execute(
                    """UPDATE faculty_roster
                       SET legacy_name=?,display_name=?,approved_email=NULL
                       WHERE id=?""",
                    (alias, alias, row["id"]),
                )

            for obsolete in ("Isaac Choutapalli", "Kamal Sarkar"):
                obsolete_id = db.execute(
                    """INSERT INTO faculty_roster
                       (program_id,legacy_name,display_name,status)
                       VALUES (?,?,?,'pending')""",
                    (self.ids["program"], obsolete, obsolete),
                ).lastrowid
                db.execute(
                    """INSERT INTO faculty_roster_courses
                       (faculty_roster_id,course_id) VALUES (?,?)""",
                    (obsolete_id, self.ids["courses"]["MECE 3320"]),
                )

            custom_id = db.execute(
                """INSERT INTO faculty_roster
                   (program_id,legacy_name,display_name,approved_email,status)
                   VALUES (?,?,?,?, 'pending')""",
                (
                    self.ids["program"],
                    "Owner Added Faculty",
                    "Owner Added Faculty",
                    "owner.added@utrgv.edu",
                ),
            ).lastrowid
            db.execute(
                """INSERT INTO faculty_roster_courses
                   (faculty_roster_id,course_id) VALUES (?,?)""",
                (custom_id, self.ids["courses"]["MECE 4350"]),
            )

            other_org = db.execute(
                "INSERT INTO organizations(name,slug) VALUES ('Other University','other-university')"
            ).lastrowid
            other_program = db.execute(
                """INSERT INTO programs(organization_id,code,name)
                   VALUES (?,'BSME','Other Mechanical Engineering')""",
                (other_org,),
            ).lastrowid
            other_course = db.execute(
                "INSERT INTO courses(program_id,code,name) VALUES (?,'MECE 3360','Other Heat Transfer')",
                (other_program,),
            ).lastrowid
            other_roster = db.execute(
                """INSERT INTO faculty_roster
                   (program_id,legacy_name,display_name,approved_email,status)
                   VALUES (?,'Constantine T','Unrelated Person',?,'pending')""",
                (other_program, "unrelated@other.edu"),
            ).lastrowid
            db.execute(
                """INSERT INTO faculty_roster_courses
                   (faculty_roster_id,course_id) VALUES (?,?)""",
                (other_roster, other_course),
            )
            db.execute("DELETE FROM schema_versions WHERE version=10")
            db.commit()

        migrated_app = create_app(self.config)
        with migrated_app.app_context():
            db = get_db()
            for canonical, original_id in alias_ids.items():
                canonical_row = db.execute(
                    """SELECT id,legacy_name,display_name,approved_email
                       FROM faculty_roster WHERE program_id=? AND legacy_name=?""",
                    (self.ids["program"], canonical),
                ).fetchone()
                self.assertIsNotNone(canonical_row)
                self.assertEqual(canonical_row["id"], original_id)
                self.assertEqual(canonical_row["display_name"], canonical)
                self.assertEqual(
                    canonical_row["approved_email"], EXPECTED_FACULTY[canonical][0]
                )
            self.assertEqual(
                db.execute(
                    """SELECT COUNT(*) FROM faculty_roster
                       WHERE program_id=? AND legacy_name IN
                             ('Constantine T','Caruntu D')""",
                    (self.ids["program"],),
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                db.execute(
                    """SELECT COUNT(*) FROM faculty_roster
                       WHERE program_id=? AND legacy_name IN
                             ('Isaac Choutapalli','Kamal Sarkar')""",
                    (self.ids["program"],),
                ).fetchone()[0],
                0,
            )
            custom = db.execute(
                "SELECT * FROM faculty_roster WHERE id=?", (custom_id,)
            ).fetchone()
            self.assertEqual(custom["approved_email"], "owner.added@utrgv.edu")
            self.assertEqual(custom["status"], "pending")
            self.assertEqual(
                db.execute(
                    """SELECT course_id FROM faculty_roster_courses
                       WHERE faculty_roster_id=?""",
                    (custom_id,),
                ).fetchone()[0],
                self.ids["courses"]["MECE 4350"],
            )
            unrelated = db.execute(
                "SELECT * FROM faculty_roster WHERE id=?", (other_roster,)
            ).fetchone()
            self.assertEqual(unrelated["legacy_name"], "Constantine T")
            self.assertEqual(unrelated["display_name"], "Unrelated Person")
            self.assertEqual(unrelated["approved_email"], "unrelated@other.edu")
            owner = db.execute(
                """SELECT u.email,m.role,pm.access_level
                   FROM users u
                   JOIN memberships m ON m.user_id=u.id
                   JOIN program_members pm ON pm.user_id=u.id
                   WHERE u.id=? AND m.organization_id=? AND pm.program_id=?""",
                (
                    self.ids["owner"],
                    self.ids["organization"],
                    self.ids["program"],
                ),
            ).fetchone()
            self.assertEqual(tuple(owner), (OWNER_EMAIL, "owner", "manager"))
            migration_event = db.execute(
                """SELECT user_id,entity_id,details_json FROM audit_events
                   WHERE action='faculty_roster_configuration'
                     AND entity_type='faculty_roster'
                     AND entity_id=?""",
                (str(self.ids["program"]),),
            ).fetchone()
            self.assertIsNotNone(migration_event)
            self.assertIsNone(migration_event["user_id"])
            migration_details = json.loads(migration_event["details_json"])
            self.assertEqual(
                migration_details,
                {
                    "approved_faculty": 13,
                    "course_assignments": 15,
                    "designated_owner": OWNER_EMAIL,
                    "migration_version": 10,
                    "account_credentials_changed": False,
                },
            )

            first_snapshot = [
                tuple(row)
                for row in db.execute(
                    """SELECT legacy_name,display_name,approved_email,user_id,status
                       FROM faculty_roster WHERE program_id=? ORDER BY id""",
                    (self.ids["program"],),
                )
            ]
            first_links = [
                tuple(row)
                for row in db.execute(
                    """SELECT frc.faculty_roster_id,frc.course_id
                       FROM faculty_roster_courses frc
                       JOIN faculty_roster fr ON fr.id=frc.faculty_roster_id
                       WHERE fr.program_id=? ORDER BY 1,2""",
                    (self.ids["program"],),
                )
            ]
        migrated_again = create_app(self.config)
        with migrated_again.app_context():
            db = get_db()
            second_snapshot = [
                tuple(row)
                for row in db.execute(
                    """SELECT legacy_name,display_name,approved_email,user_id,status
                       FROM faculty_roster WHERE program_id=? ORDER BY id""",
                    (self.ids["program"],),
                )
            ]
            second_links = [
                tuple(row)
                for row in db.execute(
                    """SELECT frc.faculty_roster_id,frc.course_id
                       FROM faculty_roster_courses frc
                       JOIN faculty_roster fr ON fr.id=frc.faculty_roster_id
                       WHERE fr.program_id=? ORDER BY 1,2""",
                    (self.ids["program"],),
                )
            ]
            self.assertEqual(second_snapshot, first_snapshot)
            self.assertEqual(second_links, first_links)
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM schema_versions WHERE version=10"
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                db.execute(
                    """SELECT COUNT(*) FROM audit_events
                       WHERE action='faculty_roster_configuration'
                         AND entity_type='faculty_roster'
                         AND entity_id=?""",
                    (str(self.ids["program"]),),
                ).fetchone()[0],
                1,
            )


if __name__ == "__main__":
    unittest.main()
