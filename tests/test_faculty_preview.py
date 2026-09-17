from __future__ import annotations

import csv
import io
import tempfile
import unittest
from pathlib import Path

from werkzeug.security import generate_password_hash

from abet_platform import create_app
from abet_platform.db import get_db


class UtrgvFacultyPreviewTests(unittest.TestCase):
    """Security and workflow contract for the owner-controlled support login."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "faculty-preview-test-secret",
                "DATABASE": str(root / "utrgv-preview.db"),
                "UPLOAD_FOLDER": str(root / "uploads"),
                "EDITION": "utrgv_mece",
                "PRODUCT_NAME": "UTRGV ME Accreditation Hub",
                "CUSTOMER_NAME": "UTRGV Department of Mechanical Engineering",
                "LEGACY_DATABASE": str(root / "missing-legacy.db"),
            }
        )
        self.owner = self.app.test_client()
        self.preview = self.app.test_client()
        self._setup_owner()
        with self.app.app_context():
            db = get_db()
            program = db.execute(
                "SELECT id,organization_id FROM programs WHERE code='BSME'"
            ).fetchone()
            self.ids = {
                "program": program["id"],
                "organization": program["organization_id"],
                "courses": {
                    row["code"]: row["id"]
                    for row in db.execute(
                        """SELECT id,code FROM courses
                           WHERE program_id=? AND code IN ('MECE 3315','MECE 3320')""",
                        (program["id"],),
                    )
                },
            }

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def csrf(client) -> str:
        with client.session_transaction() as session:
            return session["csrf_token"]

    def _setup_owner(self) -> None:
        self.owner.get("/setup")
        response = self.owner.post(
            "/setup",
            data={
                "csrf_token": self.csrf(self.owner),
                "full_name": "Isaac Choutapalli",
                "email": "isaac.palli@utrgv.edu",
                "password": "owner-password-long",
            },
        )
        self.assertEqual(response.status_code, 302)
        self._login(
            self.owner, "isaac.palli@utrgv.edu", "owner-password-long"
        )

    def _login(self, client, login: str, password: str, *, next_url: str = ""):
        with client.session_transaction() as session:
            session.clear()
        client.get("/login")
        suffix = f"?next={next_url}" if next_url else ""
        return client.post(
            f"/login{suffix}",
            data={
                "csrf_token": self.csrf(client),
                "login": login,
                "password": password,
            },
        )

    def _create_support_account(
        self,
        *,
        email: str = "faculty.view@utrgv.edu",
        username: str = "faculty-view",
        password: str = "support-temp-password",
    ):
        return self.owner.post(
            "/utrgv/support-account",
            data={
                "csrf_token": self.csrf(self.owner),
                "action": "create",
                "email": email,
                "username": username,
                "temporary_password": password,
                "confirm_temporary_password": password,
            },
        )

    def _finish_support_password_change(self) -> None:
        login = self._login(
            self.preview, "faculty-view", "support-temp-password"
        )
        self.assertEqual(login.headers["Location"], "/account/password")
        changed = self.preview.post(
            "/account/password",
            data={
                "csrf_token": self.csrf(self.preview),
                "current_password": "support-temp-password",
                "new_password": "support-final-password",
                "confirm_password": "support-final-password",
            },
        )
        self.assertEqual(changed.status_code, 302)

    def _select_scope(
        self, course_code: str, *campuses: str, client=None
    ):
        client = client or self.preview
        return client.post(
            "/utrgv/support-scope",
            data={
                "csrf_token": self.csrf(client),
                "course_id": str(self.ids["courses"][course_code]),
                "campus": list(campuses),
            },
        )

    def _assessment_payload(
        self, course_code: str, campus: str, tool: str, *, client=None
    ):
        client = client or self.owner
        with self.app.app_context():
            db = get_db()
            outcome = db.execute(
                """SELECT id FROM outcomes
                   WHERE program_id=? ORDER BY display_order,id LIMIT 1""",
                (self.ids["program"],),
            ).fetchone()[0]
            return {
                "csrf_token": self.csrf(client),
                "term_id": db.execute(
                    """SELECT id FROM academic_terms WHERE program_id=?
                       ORDER BY sort_order DESC,id DESC LIMIT 1""",
                    (self.ids["program"],),
                ).fetchone()[0],
                "course_id": self.ids["courses"][course_code],
                "outcome_id": outcome,
                "indicator_id": db.execute(
                    """SELECT id FROM performance_indicators
                       WHERE outcome_id=? ORDER BY display_order,id LIMIT 1""",
                    (outcome,),
                ).fetchone()[0],
                "rubric_id": db.execute(
                    """SELECT id FROM rubrics WHERE program_id=?
                       ORDER BY is_default DESC,id LIMIT 1""",
                    (self.ids["program"],),
                ).fetchone()[0],
                "campus": campus,
                "method": "direct",
                "assessment_tool": tool,
                "bloom_level": "Analyze",
                "target": "70",
                "expert_percent": "30",
                "practitioner_percent": "50",
                "apprentice_percent": "10",
                "novice_percent": "10",
                "rationale": "Aligned direct evidence.",
                "observations": "Students demonstrated the expected skill.",
                "action_notes": "Review again next term.",
            }

    def _seed_records(self) -> dict[str, int]:
        records = {}
        for key, course, campus in (
            ("a_e", "MECE 3315", "Edinburg"),
            ("a_b", "MECE 3315", "Brownsville"),
            ("b_e", "MECE 3320", "Edinburg"),
            ("b_b", "MECE 3320", "Brownsville"),
        ):
            response = self.owner.post(
                "/assessments/new",
                data=self._assessment_payload(course, campus, f"preview-{key}"),
            )
            self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            db = get_db()
            for row in db.execute(
                """SELECT id,assessment_tool FROM assessment_records
                   WHERE assessment_tool LIKE 'preview-%'"""
            ):
                records[row["assessment_tool"].removeprefix("preview-")] = row["id"]
            db.execute(
                """UPDATE assessment_records SET status='approved'
                   WHERE assessment_tool LIKE 'preview-%'"""
            )
            db.commit()
        return records

    def test_owner_creates_one_marked_faculty_account_without_seeded_secret(self):
        with self.app.app_context():
            db = get_db()
            self.assertTrue(
                db.execute(
                    "SELECT 1 FROM schema_versions WHERE version=12"
                ).fetchone()
            )
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM program_support_accounts").fetchone()[0],
                0,
            )

        rejected = self._create_support_account(email="yingchen.yang@utrgv.edu")
        self.assertEqual(rejected.status_code, 302)
        with self.app.app_context():
            self.assertEqual(
                get_db()
                .execute("SELECT COUNT(*) FROM program_support_accounts")
                .fetchone()[0],
                0,
            )

        created = self._create_support_account()
        self.assertEqual(created.status_code, 302)
        users_page = self.owner.get("/users")
        self.assertIn(b"Faculty View support login", users_page.data)
        self.assertIn(b"faculty.view@utrgv.edu", users_page.data)
        with self.app.app_context():
            db = get_db()
            account = db.execute(
                """SELECT psa.user_id,u.full_name,u.must_change_password,
                          m.role,pm.access_level
                   FROM program_support_accounts psa
                   JOIN users u ON u.id=psa.user_id
                   JOIN memberships m ON m.user_id=u.id
                   JOIN program_members pm ON pm.user_id=u.id
                                          AND pm.program_id=psa.program_id"""
            ).fetchone()
            self.assertEqual(account["role"], "faculty")
            self.assertEqual(account["access_level"], "editor")
            self.assertEqual(account["full_name"], "Faculty View Support")
            self.assertEqual(account["must_change_password"], 1)
            self.assertFalse(
                db.execute(
                    "SELECT 1 FROM faculty_roster WHERE user_id=?",
                    (account["user_id"],),
                ).fetchone()
            )
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM course_campus_assignments WHERE user_id=?",
                    (account["user_id"],),
                ).fetchone()[0],
                0,
            )

        renamed = self.owner.post(
            "/utrgv/support-account",
            data={
                "csrf_token": self.csrf(self.owner),
                "action": "update",
                "full_name": "Yingchen Yang",
                "email": "faculty.view@utrgv.edu",
                "username": "faculty-view",
            },
        )
        self.assertEqual(renamed.status_code, 302)
        with self.app.app_context():
            self.assertEqual(
                get_db()
                .execute(
                    """SELECT u.full_name FROM users u
                       JOIN program_support_accounts psa ON psa.user_id=u.id"""
                )
                .fetchone()[0],
                "Faculty View Support",
            )

        duplicate = self._create_support_account(
            email="another.support@utrgv.edu", username="another-support"
        )
        self.assertEqual(duplicate.status_code, 302)
        with self.app.app_context():
            self.assertEqual(
                get_db()
                .execute("SELECT COUNT(*) FROM program_support_accounts")
                .fetchone()[0],
                1,
            )

    def test_login_requires_scope_then_exact_scope_drives_every_faculty_view(self):
        records = self._seed_records()
        self._create_support_account()
        # The dedicated marker, not alphabetical program order, determines
        # which program the support credential enters.
        with self.app.app_context():
            db = get_db()
            support_id = db.execute(
                "SELECT user_id FROM program_support_accounts"
            ).fetchone()[0]
            other_program = db.execute(
                """INSERT INTO programs(organization_id,code,name)
                   VALUES (?,'OTHER','AAA Other Program')""",
                (self.ids["organization"],),
            ).lastrowid
            db.execute(
                """INSERT INTO program_members(program_id,user_id,access_level)
                   VALUES (?,?,'editor')""",
                (other_program, support_id),
            )
            db.commit()
        self._finish_support_password_change()
        no_scope = self._login(
            self.preview,
            "faculty-view",
            "support-final-password",
            next_url="/configuration",
        )
        self.assertEqual(no_scope.headers["Location"], "/utrgv/support-scope")
        with self.preview.session_transaction() as session:
            self.assertEqual(session["program_id"], self.ids["program"])
        scope_page = self.preview.get("/utrgv/support-scope")
        self.assertEqual(scope_page.status_code, 200)
        self.assertIn(b"MECE 3315", scope_page.data)
        self.assertIn(b"This is a live faculty account", scope_page.data)

        invalid = self._select_scope("MECE 3315", "Harlingen")
        self.assertEqual(invalid.status_code, 200)
        with self.app.app_context():
            db = get_db()
            support_id = db.execute(
                "SELECT user_id FROM program_support_accounts"
            ).fetchone()[0]
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM course_campus_assignments WHERE user_id=?",
                    (support_id,),
                ).fetchone()[0],
                0,
            )

        selected = self._select_scope("MECE 3315", "Edinburg")
        self.assertEqual(selected.headers["Location"], "/")
        listing = self.preview.get("/assessments")
        self.assertIn(b"preview-a_e", listing.data)
        for hidden in (b"preview-a_b", b"preview-b_e", b"preview-b_b"):
            self.assertNotIn(hidden, listing.data)
        self.assertIn(b"Faculty View support login", listing.data)
        self.assertIn(b"MECE 3315", listing.data)
        self.assertEqual(
            self.preview.get(f"/assessments/{records['a_e']}/edit").status_code,
            200,
        )
        self.assertEqual(
            self.preview.get(f"/assessments/{records['a_b']}/edit").status_code,
            403,
        )
        export = self.preview.get(
            "/export/assessments.csv?evidence_scope=all"
        )
        tools = {
            row["assessment_tool"]
            for row in csv.DictReader(io.StringIO(export.get_data(as_text=True)))
        }
        self.assertEqual(tools, {"preview-a_e"})

        switched = self._select_scope(
            "MECE 3320", "Edinburg", "Brownsville"
        )
        self.assertEqual(switched.status_code, 302)
        listing = self.preview.get("/assessments")
        self.assertIn(b"preview-b_e", listing.data)
        self.assertIn(b"preview-b_b", listing.data)
        self.assertNotIn(b"preview-a_e", listing.data)
        with self.app.app_context():
            db = get_db()
            support_id = db.execute(
                "SELECT user_id FROM program_support_accounts"
            ).fetchone()[0]
            pairs = {
                (row["course_id"], row["campus"])
                for row in db.execute(
                    """SELECT course_id,campus FROM course_campus_assignments
                       WHERE user_id=?""",
                    (support_id,),
                )
            }
            self.assertEqual(
                pairs,
                {
                    (self.ids["courses"]["MECE 3320"], "Edinburg"),
                    (self.ids["courses"]["MECE 3320"], "Brownsville"),
                },
            )
            audit = db.execute(
                """SELECT COUNT(*) FROM audit_events
                   WHERE action='update_scope'
                     AND entity_type='program_support_account'"""
            ).fetchone()[0]
            self.assertEqual(audit, 2)

        created_by_support = self.preview.post(
            "/assessments/new",
            data=self._assessment_payload(
                "MECE 3320",
                "Brownsville",
                "preview-support-created",
                client=self.preview,
            ),
        )
        self.assertEqual(created_by_support.status_code, 302)
        owner_listing = self.owner.get("/assessments")
        self.assertIn(b"preview-support-created", owner_listing.data)
        self.assertIn(
            b"Faculty View Support (support login)", owner_listing.data
        )

    def test_scope_fails_closed_if_stored_assignments_are_malformed(self):
        records = self._seed_records()
        self._create_support_account()
        self._finish_support_password_change()
        self._login(self.preview, "faculty-view", "support-final-password")
        self._select_scope("MECE 3315", "Edinburg")
        with self.app.app_context():
            db = get_db()
            support_id = db.execute(
                "SELECT user_id FROM program_support_accounts"
            ).fetchone()[0]
            other_course = self.ids["courses"]["MECE 3320"]
            # An orphan pair must not be ignored by preview validation merely
            # because the redundant course-only assignment is absent.
            db.execute(
                """INSERT INTO course_campus_assignments
                   (course_id,user_id,campus) VALUES (?,?,'Brownsville')""",
                (other_course, support_id),
            )
            db.commit()

        listing = self.preview.get("/assessments")
        for marker in (b"preview-a_e", b"preview-b_b"):
            self.assertNotIn(marker, listing.data)
        orphan_export = self.preview.get(
            "/export/assessments.csv?evidence_scope=all"
        )
        self.assertEqual(
            list(csv.DictReader(io.StringIO(orphan_export.get_data(as_text=True)))),
            [],
        )
        self.assertEqual(
            self.preview.get(f"/assessments/{records['a_e']}/edit").status_code,
            403,
        )
        self.assertEqual(
            self.preview.post(
                "/assessments/new",
                data=self._assessment_payload(
                    "MECE 3315",
                    "Edinburg",
                    "orphan-scope-write",
                    client=self.preview,
                ),
            ).status_code,
            403,
        )
        self.assertEqual(
            self._select_scope("MECE 3315", "Edinburg").status_code, 302
        )
        with self.app.app_context():
            db = get_db()
            db.execute(
                "UPDATE courses SET is_active=0 WHERE id=?",
                (self.ids["courses"]["MECE 3315"],),
            )
            db.commit()
        # A formerly valid pair for a now-inactive course must also fail closed.
        self.assertNotIn(b"preview-a_e", self.preview.get("/assessments").data)
        inactive_export = self.preview.get(
            "/export/assessments.csv?evidence_scope=all"
        )
        self.assertEqual(
            list(csv.DictReader(io.StringIO(inactive_export.get_data(as_text=True)))),
            [],
        )
        self.assertEqual(
            self.preview.post(
                "/assessments/new",
                data=self._assessment_payload(
                    "MECE 3315",
                    "Edinburg",
                    "inactive-scope-write",
                    client=self.preview,
                ),
            ).status_code,
            403,
        )
        repaired = self._select_scope("MECE 3320", "Brownsville")
        self.assertEqual(repaired.status_code, 302)
        listing = self.preview.get("/assessments")
        self.assertIn(b"preview-b_b", listing.data)
        self.assertNotIn(b"preview-a_e", listing.data)

    def test_only_owner_controls_credentials_and_disable_revokes_sessions(self):
        self._create_support_account()
        self._finish_support_password_change()
        self._login(self.preview, "faculty-view", "support-final-password")
        self._select_scope("MECE 3315", "Edinburg")
        with self.app.app_context():
            db = get_db()
            support_id = db.execute(
                "SELECT user_id FROM program_support_accounts"
            ).fetchone()[0]
            admin_id = db.execute(
                """INSERT INTO users(email,full_name,password_hash)
                   VALUES ('preview-admin@utrgv.edu','Preview Admin',?)""",
                (generate_password_hash("admin-password-long"),),
            ).lastrowid
            db.execute(
                """INSERT INTO memberships(user_id,organization_id,role)
                   VALUES (?,?,'admin')""",
                (admin_id, self.ids["organization"]),
            )
            db.execute(
                """INSERT INTO program_members(program_id,user_id,access_level)
                   VALUES (?,?,'manager')""",
                (self.ids["program"], admin_id),
            )
            db.commit()

        admin = self.app.test_client()
        self.assertEqual(
            self._login(admin, "preview-admin@utrgv.edu", "admin-password-long").status_code,
            302,
        )
        self.assertEqual(
            admin.post(
                "/utrgv/support-account",
                data={"csrf_token": self.csrf(admin), "action": "disable"},
            ).status_code,
            403,
        )
        self.assertEqual(admin.get("/utrgv/support-scope").status_code, 403)
        self.assertEqual(
            admin.post(
                f"/users/{support_id}/temporary-password",
                data={
                    "csrf_token": self.csrf(admin),
                    "temporary_password": "admin-forged-password",
                    "confirm_temporary_password": "admin-forged-password",
                },
            ).status_code,
            403,
        )

        disabled = self.owner.post(
            "/utrgv/support-account",
            data={"csrf_token": self.csrf(self.owner), "action": "disable"},
        )
        self.assertEqual(disabled.status_code, 302)
        self.assertTrue(
            self.preview.get("/").headers["Location"].startswith("/login")
        )
        rejected = self._login(
            self.preview, "faculty-view", "support-final-password"
        )
        self.assertEqual(rejected.status_code, 200)

        reactivated = self.owner.post(
            "/utrgv/support-account",
            data={
                "csrf_token": self.csrf(self.owner),
                "action": "reactivate",
                "temporary_password": "reactivated-temp-password",
                "confirm_temporary_password": "reactivated-temp-password",
            },
        )
        self.assertEqual(reactivated.status_code, 302)
        login = self._login(
            self.preview, "faculty-view", "reactivated-temp-password"
        )
        self.assertEqual(login.headers["Location"], "/account/password")


if __name__ == "__main__":
    unittest.main()
