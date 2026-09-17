from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from abet_platform import create_app
from abet_platform.db import get_db


LEGACY_SCHEMA = """
CREATE TABLE abet_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course TEXT, course_name TEXT, slo TEXT, pi TEXT, assessment_tool TEXT,
    explanation TEXT, semester TEXT, blooms_level TEXT, expert REAL,
    practitioner REAL, apprentice REAL, novice REAL, observations TEXT
);
CREATE TABLE user_drafts (user TEXT PRIMARY KEY, blob TEXT);
"""


class UtrgvEditionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.legacy = root / "abet_data.db"
        with sqlite3.connect(self.legacy) as connection:
            connection.executescript(LEGACY_SCHEMA)
            connection.executemany(
                """INSERT INTO abet_entries
                   (course,course_name,slo,pi,assessment_tool,explanation,semester,blooms_level,
                    expert,practitioner,apprentice,novice,observations)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [
                    (
                        "MECE 3320", "Measurements & Instrumentation", "SLO1",
                        "PI‑3: Able to solve Problem", "Lab practical", "Aligned direct evidence",
                        "Fall 2024", "Analyze", 45.25, 35.0, 14.75, 5.0, "Retain the new lab sequence",
                    ),
                    (
                        "MECE 3315", "Fluid Mechanics", "SLO1", "", "Final examination",
                        "Legacy row without a PI", "Fall 2024", "Analyze", 40.0, 30.0, 20.0, 10.0,
                        "Map the indicator during review",
                    ),
                ],
            )
            connection.execute(
                "INSERT INTO user_drafts(user,blob) VALUES (?,?)",
                (
                    "Super User",
                    json.dumps([{"course": "MECE 3380", "semester": "Fall 2020", "slo": "SLO1", "pi": "PI-3"}]),
                ),
            )
        self.source_before = self.legacy.read_bytes()
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "utrgv-test-secret",
                "DATABASE": str(root / "utrgv.db"),
                "UPLOAD_FOLDER": str(root / "uploads"),
                "EDITION": "utrgv_mece",
                "PRODUCT_NAME": "UTRGV ME Accreditation Hub",
                "CUSTOMER_NAME": "UTRGV Department of Mechanical Engineering",
                "LEGACY_DATABASE": str(self.legacy),
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def csrf(self):
        with self.client.session_transaction() as session:
            return session["csrf_token"]

    def setup_and_login_owner(self):
        page = self.client.get("/setup")
        self.assertIn(b"Initialize UTRGV Mechanical Engineering", page.data)
        response = self.client.post(
            "/setup",
            data={
                "csrf_token": self.csrf(),
                "full_name": "Accreditation Director",
                "email": "isaac.palli@utrgv.edu",
                "password": "owner-password-long",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.client.get("/login")
        response = self.client.post(
            "/login",
            data={"csrf_token": self.csrf(), "login": "isaac.palli@utrgv.edu", "password": "owner-password-long"},
        )
        self.assertEqual(response.status_code, 302)

    def assessment_payload(
        self,
        *,
        course_code: str,
        assessment_tool: str,
        observations: str = "",
        campus: str = "Edinburg",
    ):
        """Build a valid assessment submission for a seeded UTRGV course."""
        with self.app.app_context():
            db = get_db()
            course = db.execute("SELECT id FROM courses WHERE code=?", (course_code,)).fetchone()
            term = db.execute(
                "SELECT id FROM academic_terms ORDER BY sort_order DESC LIMIT 1"
            ).fetchone()
            outcome = db.execute(
                "SELECT id FROM outcomes WHERE code='SLO1'"
            ).fetchone()
            indicator = db.execute(
                """SELECT id FROM performance_indicators
                   WHERE outcome_id=? ORDER BY display_order,id LIMIT 1""",
                (outcome["id"],),
            ).fetchone()
            rubric = db.execute(
                "SELECT id FROM rubrics ORDER BY is_default DESC,id LIMIT 1"
            ).fetchone()
        payload = {
            "csrf_token": self.csrf(),
            "term_id": term["id"],
            "course_id": course["id"],
            "outcome_id": outcome["id"],
            "indicator_id": indicator["id"],
            "rubric_id": rubric["id"],
            "campus": campus,
            "method": "direct",
            "assessment_tool": assessment_tool,
            "bloom_level": "Analyze",
            "target": "70",
            "expert_percent": "30",
            "practitioner_percent": "50",
            "apprentice_percent": "10",
            "novice_percent": "10",
            "rationale": "Aligned direct evidence",
            "observations": observations or "Assessment interpretation.",
            "action_notes": "Review the result at the next faculty meeting.",
        }
        return payload

    def test_exact_customer_seed_is_complete_and_idempotent(self):
        self.setup_and_login_owner()
        with self.app.app_context():
            db = get_db()
            self.assertEqual(db.execute("SELECT COUNT(*) FROM courses").fetchone()[0], 16)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM academic_terms").fetchone()[0], 13)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM faculty_roster").fetchone()[0], 13)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM faculty_roster_courses").fetchone()[0], 15)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM outcomes WHERE code LIKE 'SLO%'").fetchone()[0], 7)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM performance_indicators").fetchone()[0], 28)
            roster_map = {
                row["legacy_name"]: tuple(row["courses"].split(","))
                for row in db.execute(
                    """SELECT fr.legacy_name,GROUP_CONCAT(c.code, ',') AS courses
                       FROM faculty_roster fr
                       JOIN faculty_roster_courses frc ON frc.faculty_roster_id=fr.id
                       JOIN courses c ON c.id=frc.course_id
                       GROUP BY fr.id ORDER BY fr.legacy_name"""
                )
            }
            from abet_platform.utrgv_config import FACULTY_COURSES, TERMS, seed_utrgv_mece

            self.assertEqual(roster_map, {name: tuple(courses) for name, courses in FACULTY_COURSES})
            seeded_terms = tuple(
                row["name"]
                for row in db.execute("SELECT name FROM academic_terms ORDER BY sort_order")
            )
            self.assertEqual(seeded_terms, TERMS)
            org = db.execute("SELECT * FROM organizations").fetchone()
            self.assertEqual(org["primary_color"], "#003638")

            program = db.execute("SELECT * FROM programs").fetchone()
            with db:
                seed_utrgv_mece(db, org["id"], program["id"])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM courses").fetchone()[0], 16)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM faculty_roster_courses").fetchone()[0], 15)

    def test_legacy_archive_import_is_exact_read_only_and_idempotent(self):
        self.setup_and_login_owner()
        archive = self.client.get("/utrgv/legacy")
        self.assertEqual(archive.status_code, 200)
        self.assertIn(b"2", archive.data)
        self.assertIn(b"Unsent drafts", archive.data)
        response = self.client.post(
            "/utrgv/legacy/import",
            data={"csrf_token": self.csrf(), "campus": "Edinburg"},
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            db = get_db()
            self.assertEqual(db.execute("SELECT COUNT(*) FROM assessment_records").fetchone()[0], 2)
            legacy = db.execute(
                "SELECT * FROM legacy_import_items WHERE source_record_id=1"
            ).fetchone()
            self.assertEqual(legacy["expert_percent"], 45.25)
            self.assertEqual(legacy["practitioner_percent"], 35.0)
            unmapped = db.execute(
                """SELECT pi.description FROM legacy_import_items li
                   JOIN assessment_records ar ON ar.id=li.assessment_id
                   JOIN performance_indicators pi ON pi.id=ar.indicator_id
                   WHERE li.source_record_id=2"""
            ).fetchone()[0]
            self.assertIn("Unmapped source PI", unmapped)
        self.client.post(
            "/utrgv/legacy/import",
            data={"csrf_token": self.csrf(), "campus": "Edinburg"},
        )
        with self.app.app_context():
            self.assertEqual(get_db().execute("SELECT COUNT(*) FROM assessment_records").fetchone()[0], 2)
        self.assertEqual(self.legacy.read_bytes(), self.source_before)

    def test_roster_activation_forces_password_change_and_scopes_courses(self):
        self.setup_and_login_owner()
        with self.app.app_context():
            roster_id = get_db().execute(
                "SELECT id FROM faculty_roster WHERE legacy_name='Nadim Zgheib'"
            ).fetchone()[0]
        response = self.client.post(
            f"/utrgv/faculty/{roster_id}/activate",
            data={
                "csrf_token": self.csrf(),
                "email": "spoofed@utrgv.edu",
                "username": "Nadim Zgheib",
                "temporary_password": "temporary-password",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.client.post("/logout", data={"csrf_token": self.csrf()})
        self.client.get("/login")
        response = self.client.post(
            "/login",
            data={"csrf_token": self.csrf(), "login": "nadim zgheib", "password": "temporary-password"},
        )
        self.assertEqual(response.headers["Location"], "/account/password")
        self.assertEqual(self.client.get("/").headers["Location"], "/account/password")
        response = self.client.post(
            "/account/password",
            data={
                "csrf_token": self.csrf(),
                "current_password": "temporary-password",
                "new_password": "replacement-password",
                "confirm_password": "replacement-password",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.client.get("/login")
        self.client.post(
            "/login",
            data={"csrf_token": self.csrf(), "login": "Nadim Zgheib", "password": "replacement-password"},
        )
        with self.app.app_context():
            courses = get_db().execute(
                """SELECT c.code FROM course_assignments ca JOIN courses c ON c.id=ca.course_id
                   JOIN users u ON u.id=ca.user_id WHERE u.username='Nadim Zgheib'"""
            ).fetchall()
            self.assertEqual([row["code"] for row in courses], ["MECE 3315"])
            self.assertEqual(
                get_db().execute("SELECT must_change_password FROM users WHERE username='Nadim Zgheib'").fetchone()[0],
                0,
            )

    def test_activated_faculty_can_create_and_edit_only_owned_assigned_course_data(self):
        self.setup_and_login_owner()
        with self.app.app_context():
            db = get_db()
            roster_id = db.execute(
                "SELECT id FROM faculty_roster WHERE legacy_name='Nadim Zgheib'"
            ).fetchone()[0]

        activation = self.client.post(
            f"/utrgv/faculty/{roster_id}/activate",
            data={
                "csrf_token": self.csrf(),
                "email": "spoofed@utrgv.edu",
                "username": "Nadim Zgheib",
                "temporary_password": "temporary-password",
            },
        )
        self.assertEqual(activation.status_code, 302)

        # Create manager-owned records both inside and outside the faculty member's
        # course scope. These exercise ownership and course checks independently.
        response = self.client.post(
            "/assessments/new",
            data=self.assessment_payload(
                course_code="MECE 3315", assessment_tool="Manager record in assigned course"
            ),
        )
        self.assertEqual(response.status_code, 302)
        response = self.client.post(
            "/assessments/new",
            data=self.assessment_payload(
                course_code="MECE 3320", assessment_tool="Manager record outside assigned course"
            ),
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            db = get_db()
            manager_same_course_id = db.execute(
                "SELECT id FROM assessment_records WHERE assessment_tool='Manager record in assigned course'"
            ).fetchone()[0]
            manager_other_course_id = db.execute(
                "SELECT id FROM assessment_records WHERE assessment_tool='Manager record outside assigned course'"
            ).fetchone()[0]

        self.client.post("/logout", data={"csrf_token": self.csrf()})
        self.client.get("/login")
        login = self.client.post(
            "/login",
            data={
                "csrf_token": self.csrf(),
                "login": "nadim zgheib",
                "password": "temporary-password",
            },
        )
        self.assertEqual(login.headers["Location"], "/account/password")
        changed = self.client.post(
            "/account/password",
            data={
                "csrf_token": self.csrf(),
                "current_password": "temporary-password",
                "new_password": "replacement-password",
                "confirm_password": "replacement-password",
            },
        )
        self.assertEqual(changed.status_code, 302)
        self.client.get("/login")
        login = self.client.post(
            "/login",
            data={
                "csrf_token": self.csrf(),
                "login": "Nadim Zgheib",
                "password": "replacement-password",
            },
        )
        self.assertEqual(login.status_code, 302)

        new_form = self.client.get("/assessments/new")
        self.assertEqual(new_form.status_code, 200)
        self.assertIn(b"MECE 3315", new_form.data)
        self.assertNotIn(b"MECE 3320", new_form.data)

        created = self.client.post(
            "/assessments/new",
            data=self.assessment_payload(
                course_code="MECE 3315",
                assessment_tool="Faculty-owned lab assessment",
                observations="Initial faculty interpretation.",
            ),
        )
        self.assertEqual(created.status_code, 302)
        with self.app.app_context():
            db = get_db()
            faculty = db.execute(
                "SELECT id FROM users WHERE username='Nadim Zgheib'"
            ).fetchone()
            faculty_record = db.execute(
                """SELECT ar.id,ar.collected_by,ar.course_id,c.code,ar.status,
                          ar.record_version
                   FROM assessment_records ar JOIN courses c ON c.id=ar.course_id
                   WHERE ar.assessment_tool='Faculty-owned lab assessment'"""
            ).fetchone()
            self.assertEqual(faculty_record["collected_by"], faculty["id"])
            self.assertEqual(faculty_record["code"], "MECE 3315")
            self.assertEqual(faculty_record["status"], "draft")

        edit_payload = self.assessment_payload(
            course_code="MECE 3315",
            assessment_tool="Faculty-owned lab assessment",
            observations="Revised faculty interpretation.",
        )
        edit_payload["record_version"] = str(faculty_record["record_version"])
        edited = self.client.post(
            f"/assessments/{faculty_record['id']}/edit",
            data=edit_payload,
        )
        self.assertEqual(edited.status_code, 302)
        with self.app.app_context():
            observation = get_db().execute(
                "SELECT observations FROM assessment_records WHERE id=?",
                (faculty_record["id"],),
            ).fetchone()[0]
            self.assertEqual(observation, "Revised faculty interpretation.")

        # A crafted POST cannot create a record for an unassigned course.
        with self.app.app_context():
            count_before = get_db().execute("SELECT COUNT(*) FROM assessment_records").fetchone()[0]
        unassigned_create = self.client.post(
            "/assessments/new",
            data=self.assessment_payload(
                course_code="MECE 3320", assessment_tool="Unauthorized course record"
            ),
        )
        self.assertEqual(unassigned_create.status_code, 403)
        with self.app.app_context():
            self.assertEqual(
                get_db().execute("SELECT COUNT(*) FROM assessment_records").fetchone()[0],
                count_before,
            )

        # Ownership is enforced even when two records belong to the same assigned
        # course, and course scope is enforced before an outside record is shown.
        self.assertEqual(
            self.client.post(
                f"/assessments/{manager_same_course_id}/edit",
                data={"csrf_token": self.csrf()},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                f"/assessments/{manager_same_course_id}/status",
                data={"csrf_token": self.csrf(), "action": "submit"},
            ).status_code,
            403,
        )
        manager_view = self.client.get(f"/assessments/{manager_same_course_id}/edit")
        self.assertEqual(manager_view.status_code, 200)
        self.assertNotIn(b"Submit for review", manager_view.data)
        self.assertEqual(
            self.client.get(f"/assessments/{manager_other_course_id}/edit").status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                f"/assessments/{manager_other_course_id}/edit",
                data={"csrf_token": self.csrf()},
            ).status_code,
            403,
        )

        # Revoking a course assignment takes effect immediately at every write
        # endpoint, including crafted status and evidence requests. Restoring the
        # assignment then restores the normal faculty workflow.
        with self.app.app_context():
            db = get_db()
            db.execute(
                "DELETE FROM course_assignments WHERE user_id=? AND course_id=?",
                (faculty["id"], faculty_record["course_id"]),
            )
            db.execute(
                """DELETE FROM course_campus_assignments
                   WHERE user_id=? AND course_id=?""",
                (faculty["id"], faculty_record["course_id"]),
            )
            db.commit()
        self.assertEqual(
            self.client.post(
                f"/assessments/{faculty_record['id']}/status",
                data={"csrf_token": self.csrf(), "action": "submit"},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                f"/assessments/{faculty_record['id']}/evidence",
                data={
                    "csrf_token": self.csrf(),
                    "title": "Out-of-scope evidence",
                    "source_url": "https://example.edu/evidence",
                },
            ).status_code,
            403,
        )
        with self.app.app_context():
            db = get_db()
            db.execute(
                "INSERT INTO course_assignments(course_id,user_id) VALUES (?,?)",
                (faculty_record["course_id"], faculty["id"]),
            )
            db.executemany(
                """INSERT INTO course_campus_assignments
                   (course_id,user_id,campus) VALUES (?,?,?)""",
                [
                    (faculty_record["course_id"], faculty["id"], campus)
                    for campus in ("Edinburg", "Brownsville")
                ],
            )
            db.commit()

        submitted = self.client.post(
            f"/assessments/{faculty_record['id']}/status",
            data={"csrf_token": self.csrf(), "action": "submit"},
        )
        self.assertEqual(submitted.status_code, 302)
        reopen_page = self.client.get(f"/assessments/{faculty_record['id']}/edit")
        self.assertEqual(reopen_page.status_code, 200)
        self.assertIn(b"Editing will reopen this assessment for review", reopen_page.data)
        with self.app.app_context():
            submitted_version = get_db().execute(
                "SELECT record_version FROM assessment_records WHERE id=?",
                (faculty_record["id"],),
            ).fetchone()[0]
        reopened_payload = self.assessment_payload(
            course_code="MECE 3315", assessment_tool="Faculty revision after submission"
        )
        reopened_payload["record_version"] = str(submitted_version)
        self.assertEqual(
            self.client.post(
                f"/assessments/{faculty_record['id']}/edit",
                data=reopened_payload,
            ).status_code,
            302,
        )
        with self.app.app_context():
            reopened = get_db().execute(
                """SELECT status,submitted_at,approved_at,approved_by,assessment_tool
                   FROM assessment_records WHERE id=?""",
                (faculty_record["id"],),
            ).fetchone()
            self.assertEqual(reopened["status"], "draft")
            self.assertIsNone(reopened["submitted_at"])
            self.assertIsNone(reopened["approved_at"])
            self.assertIsNone(reopened["approved_by"])
            self.assertEqual(
                reopened["assessment_tool"], "Faculty revision after submission"
            )

        # Faculty accounts cannot activate roster identities or administer users.
        with self.app.app_context():
            pending_roster_id = get_db().execute(
                "SELECT id FROM faculty_roster WHERE user_id IS NULL ORDER BY id LIMIT 1"
            ).fetchone()[0]
        self.assertEqual(self.client.get("/users").status_code, 403)
        self.assertEqual(
            self.client.post(
                f"/utrgv/faculty/{pending_roster_id}/activate",
                data={"csrf_token": self.csrf()},
            ).status_code,
            403,
        )


if __name__ == "__main__":
    unittest.main()
