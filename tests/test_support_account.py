from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from werkzeug.security import generate_password_hash

from abet_platform import create_app
from abet_platform.db import get_db


class FacultyViewSupportAccountTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "support-account-tests",
                "DATABASE": str(root / "utrgv.db"),
                "UPLOAD_FOLDER": str(root / "uploads"),
                "EDITION": "utrgv_mece",
                "PRODUCT_NAME": "UTRGV ME Accreditation Hub",
            }
        )
        self.client = self.app.test_client()
        self.client.get("/setup")
        response = self.client.post(
            "/setup",
            data={
                "csrf_token": self.csrf(),
                "full_name": "Isaac Choutapalli",
                "email": "isaac.palli@utrgv.edu",
                "password": "owner-password-long",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.client.get("/login")
        response = self.client.post(
            "/login",
            data={
                "csrf_token": self.csrf(),
                "login": "isaac.palli@utrgv.edu",
                "password": "owner-password-long",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            db = get_db()
            program = db.execute("SELECT * FROM programs WHERE code='BSME'").fetchone()
            owner = db.execute(
                "SELECT id FROM users WHERE email='isaac.palli@utrgv.edu'"
            ).fetchone()
            self.program_id = program["id"]
            self.organization_id = program["organization_id"]
            self.owner_id = owner["id"]
            self.course_ids = {
                row["code"]: row["id"]
                for row in db.execute(
                    "SELECT id,code FROM courses WHERE program_id=?",
                    (self.program_id,),
                )
            }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def csrf(self) -> str:
        with self.client.session_transaction() as session:
            return session["csrf_token"]

    def create_support(self) -> int:
        response = self.client.post(
            "/utrgv/support-account",
            data={
                "csrf_token": self.csrf(),
                "action": "create",
                # Crafted names are ignored: this credential has immutable,
                # marker-aware provenance and cannot impersonate faculty.
                "full_name": "Yingchen Yang",
                "email": "faculty.view@utrgv.edu",
                "username": "faculty.view",
                "temporary_password": "temporary-support-password",
                "confirm_temporary_password": "temporary-support-password",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            return get_db().execute(
                "SELECT user_id FROM program_support_accounts WHERE program_id=?",
                (self.program_id,),
            ).fetchone()[0]

    def as_user(self, user_id: int) -> None:
        with self.client.session_transaction() as session:
            session.clear()
            session["user_id"] = user_id
            session["organization_id"] = self.organization_id
            session["program_id"] = self.program_id
            session["csrf_token"] = "support-account-csrf"

    def test_owner_creates_one_explicit_faculty_editor_without_default_scope(self):
        support_id = self.create_support()
        with self.app.app_context():
            db = get_db()
            account = db.execute(
                """SELECT u.email,u.username,u.full_name,u.must_change_password,m.role,
                          pm.access_level,psa.configured_by
                     FROM program_support_accounts psa
                     JOIN users u ON u.id=psa.user_id
                     JOIN memberships m ON m.user_id=u.id
                     JOIN programs p ON p.id=psa.program_id
                     JOIN program_members pm ON pm.program_id=psa.program_id
                                            AND pm.user_id=psa.user_id
                    WHERE psa.program_id=? AND m.organization_id=p.organization_id""",
                (self.program_id,),
            ).fetchone()
            self.assertEqual(account["email"], "faculty.view@utrgv.edu")
            self.assertEqual(account["full_name"], "Faculty View Support")
            self.assertEqual(account["username"], "faculty.view")
            self.assertEqual(account["role"], "faculty")
            self.assertEqual(account["access_level"], "editor")
            self.assertEqual(account["configured_by"], self.owner_id)
            self.assertEqual(account["must_change_password"], 1)
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM course_campus_assignments WHERE user_id=?",
                    (support_id,),
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM schema_versions WHERE version=12"
                ).fetchone()[0],
                1,
            )

        renamed = self.client.post(
            "/utrgv/support-account",
            data={
                "csrf_token": self.csrf(),
                "action": "update",
                "full_name": "Robert Jones",
                "email": "faculty.view@utrgv.edu",
                "username": "faculty.view",
            },
        )
        self.assertEqual(renamed.status_code, 302)
        with self.app.app_context():
            self.assertEqual(
                get_db().execute(
                    "SELECT full_name FROM users WHERE id=?", (support_id,)
                ).fetchone()[0],
                "Faculty View Support",
            )

        duplicate = self.client.post(
            "/utrgv/support-account",
            data={
                "csrf_token": self.csrf(),
                "action": "create",
                "full_name": "Second Support",
                "email": "second.support@utrgv.edu",
                "temporary_password": "another-temporary-password",
                "confirm_temporary_password": "another-temporary-password",
            },
        )
        self.assertEqual(duplicate.status_code, 302)
        with self.app.app_context():
            self.assertEqual(
                get_db().execute(
                    "SELECT COUNT(*) FROM program_support_accounts WHERE program_id=?",
                    (self.program_id,),
                ).fetchone()[0],
                1,
            )

    def test_login_requires_password_then_scope_and_scope_is_real_and_audited(self):
        support_id = self.create_support()
        self.client.post("/logout", data={"csrf_token": self.csrf()})
        self.client.get("/login")
        login = self.client.post(
            "/login?next=/users",
            data={
                "csrf_token": self.csrf(),
                "login": "faculty.view",
                "password": "temporary-support-password",
            },
        )
        self.assertEqual(login.headers["Location"], "/account/password")
        changed = self.client.post(
            "/account/password",
            data={
                "csrf_token": self.csrf(),
                "current_password": "temporary-support-password",
                "new_password": "replacement-support-password",
                "confirm_password": "replacement-support-password",
            },
        )
        self.assertEqual(changed.status_code, 302)
        self.client.get("/login")
        login = self.client.post(
            "/login?next=/users",
            data={
                "csrf_token": self.csrf(),
                "login": "faculty.view",
                "password": "replacement-support-password",
            },
        )
        self.assertEqual(login.headers["Location"], "/utrgv/support-scope")
        scope_page = self.client.get("/utrgv/support-scope")
        self.assertEqual(scope_page.status_code, 200)
        self.assertIn(b"not a demonstration sandbox", scope_page.data)

        course_id = self.course_ids["MECE 3315"]
        selected = self.client.post(
            "/utrgv/support-scope",
            data={
                "csrf_token": self.csrf(),
                "course_id": course_id,
                "campus": ["Edinburg", "Brownsville"],
            },
        )
        self.assertEqual(selected.headers["Location"], "/")
        with self.app.app_context():
            db = get_db()
            pairs = db.execute(
                """SELECT course_id,campus FROM course_campus_assignments
                   WHERE user_id=? ORDER BY campus""",
                (support_id,),
            ).fetchall()
            self.assertEqual(
                {(row["course_id"], row["campus"]) for row in pairs},
                {(course_id, "Edinburg"), (course_id, "Brownsville")},
            )
            event = db.execute(
                """SELECT details_json FROM audit_events
                   WHERE user_id=? AND action='update_scope'
                   ORDER BY id DESC LIMIT 1""",
                (support_id,),
            ).fetchone()
            details = json.loads(event["details_json"])
            self.assertTrue(details["writes_are_real_and_audited"])
        dashboard = self.client.get("/")
        self.assertIn(b"This is not a sandbox", dashboard.data)
        self.assertEqual(self.client.get("/users").status_code, 403)
        self.assertEqual(
            self.client.post(
                "/utrgv/support-account",
                data={"csrf_token": self.csrf(), "action": "disable"},
            ).status_code,
            403,
        )

    def test_non_owner_cannot_reset_or_reconfigure_marked_account(self):
        support_id = self.create_support()
        with self.app.app_context():
            db = get_db()
            admin_id = db.execute(
                """INSERT INTO users(email,full_name,password_hash)
                   VALUES ('support-admin@utrgv.edu','Support Admin',?)""",
                (generate_password_hash("admin-password-long"),),
            ).lastrowid
            db.execute(
                "INSERT INTO memberships VALUES (?,?,'admin',CURRENT_TIMESTAMP)",
                (admin_id, self.organization_id),
            )
            db.execute(
                "INSERT INTO program_members VALUES (?,?,'manager')",
                (self.program_id, admin_id),
            )
            db.commit()
        self.as_user(admin_id)
        reset = self.client.post(
            f"/users/{support_id}/temporary-password",
            data={
                "csrf_token": self.csrf(),
                "temporary_password": "admin-chosen-password",
                "confirm_temporary_password": "admin-chosen-password",
            },
        )
        self.assertEqual(reset.status_code, 403)
        self.assertEqual(
            self.client.post(
                "/utrgv/support-account",
                data={"csrf_token": self.csrf(), "action": "disable"},
            ).status_code,
            403,
        )


if __name__ == "__main__":
    unittest.main()
