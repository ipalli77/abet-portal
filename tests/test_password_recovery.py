from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

from abet_platform import create_app
from abet_platform.db import get_db


class PasswordRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
                "DATABASE": str(root / "test.db"),
                "UPLOAD_FOLDER": str(root / "uploads"),
            }
        )
        self.client = self.app.test_client()
        self.client.get("/setup")
        self.client.post(
            "/setup",
            data={
                "csrf_token": self.csrf(),
                "institution": "Example University",
                "program_name": "Mechanical Engineering",
                "program_code": "BSME",
                "full_name": "Program Owner",
                "email": "owner@example.edu",
                "password": "owner-password-long",
            },
        )
        self.client.get("/login")
        self.client.post(
            "/login",
            data={
                "csrf_token": self.csrf(),
                "login": "owner@example.edu",
                "password": "owner-password-long",
            },
        )
        with self.app.app_context():
            db = get_db()
            self.owner_id = db.execute(
                "SELECT id FROM users WHERE email='owner@example.edu'"
            ).fetchone()[0]
            self.organization_id = db.execute("SELECT id FROM organizations").fetchone()[0]
            self.program_id = db.execute("SELECT id FROM programs").fetchone()[0]
            self.faculty_id = db.execute(
                """INSERT INTO users(email,username,full_name,password_hash)
                   VALUES (?,?,?,?)""",
                (
                    "faculty@example.edu",
                    "faculty member",
                    "Faculty Member",
                    generate_password_hash("faculty-password-long"),
                ),
            ).lastrowid
            db.execute(
                "INSERT INTO memberships(user_id,organization_id,role) VALUES (?,?,'faculty')",
                (self.faculty_id, self.organization_id),
            )
            db.execute(
                "INSERT INTO program_members(program_id,user_id,access_level) VALUES (?,?,'editor')",
                (self.program_id, self.faculty_id),
            )
            db.commit()

    def tearDown(self):
        self.temp.cleanup()

    def csrf(self):
        with self.client.session_transaction() as session:
            return session["csrf_token"]

    def test_forgot_page_is_non_enumerating_guidance_and_login_copy_is_removed(self):
        self.client.post("/logout", data={"csrf_token": self.csrf()})
        response = self.client.get("/forgot-password")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Faculty and reviewers", response.data)
        self.assertIn(b"Program owners", response.data)
        self.assertNotIn(b'name="login"', response.data)
        self.client.get("/login")
        self.assertEqual(
            self.client.post(
                "/forgot-password", data={"csrf_token": self.csrf()}
            ).status_code,
            405,
        )

        login = self.client.get("/login")
        self.assertIn(b"Forgot password?", login.data)
        self.assertNotIn(b"Turn assessment evidence", login.data)
        self.assertNotIn(b"Securely collect, analyze", login.data)

    def test_owner_sets_temporary_password_without_changing_access(self):
        with self.app.app_context():
            db = get_db()
            before = db.execute(
                """SELECT u.email,u.username,u.full_name,u.is_active,m.role,pm.access_level
                     FROM users u JOIN memberships m ON m.user_id=u.id
                     JOIN program_members pm ON pm.user_id=u.id
                    WHERE u.id=?""",
                (self.faculty_id,),
            ).fetchone()
            db.execute(
                "INSERT INTO login_attempts(email,ip_address,success) VALUES (?,?,0)",
                ("faculty member", "127.0.0.1"),
            )
            db.commit()

        response = self.client.post(
            f"/users/{self.faculty_id}/temporary-password",
            data={
                "csrf_token": self.csrf(),
                "temporary_password": "temporary-password-new",
                "confirm_temporary_password": "temporary-password-new",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            db = get_db()
            after = db.execute(
                """SELECT u.email,u.username,u.full_name,u.is_active,u.must_change_password,
                          u.password_hash,m.role,pm.access_level
                     FROM users u JOIN memberships m ON m.user_id=u.id
                     JOIN program_members pm ON pm.user_id=u.id
                    WHERE u.id=?""",
                (self.faculty_id,),
            ).fetchone()
            for field in ("email", "username", "full_name", "is_active", "role", "access_level"):
                self.assertEqual(before[field], after[field])
            self.assertEqual(after["must_change_password"], 1)
            self.assertTrue(check_password_hash(after["password_hash"], "temporary-password-new"))
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM login_attempts WHERE email='faculty member'"
                ).fetchone()[0],
                0,
            )
            event = db.execute(
                """SELECT action,entity_type,entity_id,details_json FROM audit_events
                    WHERE action='reset' ORDER BY id DESC LIMIT 1"""
            ).fetchone()
            self.assertEqual((event["entity_type"], event["entity_id"]), ("password", str(self.faculty_id)))
            self.assertEqual(json.loads(event["details_json"])["force_password_change"], True)
            self.assertNotIn("temporary-password-new", event["details_json"])

        self.client.post("/logout", data={"csrf_token": self.csrf()})
        self.client.get("/login")
        login = self.client.post(
            "/login",
            data={
                "csrf_token": self.csrf(),
                "login": "faculty member",
                "password": "temporary-password-new",
            },
        )
        self.assertEqual(login.headers["Location"], "/account/password")

    def test_reset_validates_csrf_confirmation_and_tenant_scope(self):
        self.assertEqual(
            self.client.post(
                f"/users/{self.faculty_id}/temporary-password",
                data={
                    "temporary_password": "temporary-password-new",
                    "confirm_temporary_password": "temporary-password-new",
                },
            ).status_code,
            400,
        )
        mismatch = self.client.post(
            f"/users/{self.faculty_id}/temporary-password",
            data={
                "csrf_token": self.csrf(),
                "temporary_password": "temporary-password-new",
                "confirm_temporary_password": "different-password-new",
            },
            follow_redirects=True,
        )
        self.assertIn(b"Temporary password entries do not match", mismatch.data)
        with self.app.app_context():
            db = get_db()
            other_org = db.execute(
                "INSERT INTO organizations(name,slug) VALUES ('Other University','other')"
            ).lastrowid
            outsider = db.execute(
                "INSERT INTO users(email,full_name,password_hash) VALUES (?,?,?)",
                ("outside@example.edu", "Outside User", generate_password_hash("outside-password-long")),
            ).lastrowid
            db.execute(
                "INSERT INTO memberships(user_id,organization_id,role) VALUES (?,?,'faculty')",
                (outsider, other_org),
            )
            db.commit()
        cross_tenant = self.client.post(
            f"/users/{outsider}/temporary-password",
            data={
                "csrf_token": self.csrf(),
                "temporary_password": "temporary-password-new",
                "confirm_temporary_password": "temporary-password-new",
            },
        )
        self.assertEqual(cross_tenant.status_code, 404)

    def test_non_owner_admin_cannot_reset_or_overwrite_owner(self):
        with self.app.app_context():
            db = get_db()
            admin_id = db.execute(
                "INSERT INTO users(email,full_name,password_hash) VALUES (?,?,?)",
                ("admin@example.edu", "Administrator", generate_password_hash("admin-password-long")),
            ).lastrowid
            db.execute(
                "INSERT INTO memberships(user_id,organization_id,role) VALUES (?,?,'admin')",
                (admin_id, self.organization_id),
            )
            db.commit()
        with self.client.session_transaction() as session:
            session["user_id"] = admin_id
            session["organization_id"] = self.organization_id
            session["program_id"] = self.program_id

        reset = self.client.post(
            f"/users/{self.owner_id}/temporary-password",
            data={
                "csrf_token": self.csrf(),
                "temporary_password": "temporary-password-new",
                "confirm_temporary_password": "temporary-password-new",
            },
        )
        self.assertEqual(reset.status_code, 403)
        overwrite = self.client.post(
            "/users",
            data={
                "csrf_token": self.csrf(),
                "email": "owner@example.edu",
                "full_name": "Changed Owner",
                "role": "faculty",
                "temporary_password": "temporary-password-new",
            },
        )
        self.assertEqual(overwrite.status_code, 403)
        with self.app.app_context():
            owner = get_db().execute(
                "SELECT full_name,password_hash FROM users WHERE id=?", (self.owner_id,)
            ).fetchone()
            self.assertEqual(owner["full_name"], "Program Owner")
            self.assertTrue(check_password_hash(owner["password_hash"], "owner-password-long"))


if __name__ == "__main__":
    unittest.main()
