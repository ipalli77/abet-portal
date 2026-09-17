from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from werkzeug.security import generate_password_hash

from abet_platform import create_app
from abet_platform.db import get_db


class WorkflowIntegrityTests(unittest.TestCase):
    """Security and review-integrity contracts for mutable assessment evidence."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "workflow-integrity-test-secret",
                "DATABASE": str(root / "workflow.db"),
                "UPLOAD_FOLDER": str(root / "uploads"),
                "EDITION": "utrgv_mece",
                "PRODUCT_NAME": "UTRGV ME Accreditation Hub",
                "CUSTOMER_NAME": "UTRGV Department of Mechanical Engineering",
            }
        )
        self.client = self.app.test_client()
        self.client.get("/setup")
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

        with self.app.app_context():
            db = get_db()
            program = db.execute("SELECT * FROM programs WHERE code='BSME'").fetchone()
            owner = db.execute(
                "SELECT id FROM users WHERE email='isaac.palli@utrgv.edu'"
            ).fetchone()
            faculty_id = db.execute(
                "INSERT INTO users(email,full_name,password_hash) VALUES (?,?,?)",
                (
                    "assigned.faculty@utrgv.edu",
                    "Assigned Faculty",
                    generate_password_hash("faculty-password-long"),
                ),
            ).lastrowid
            db.execute(
                "INSERT INTO memberships(user_id,organization_id,role) VALUES (?,?,'faculty')",
                (faculty_id, program["organization_id"]),
            )
            db.execute(
                "INSERT INTO program_members(program_id,user_id,access_level) VALUES (?,?,'editor')",
                (program["id"], faculty_id),
            )
            courses = {
                row["code"]: row["id"]
                for row in db.execute(
                    "SELECT id,code FROM courses WHERE program_id=?",
                    (program["id"],),
                )
            }
            db.execute(
                "INSERT INTO course_assignments(course_id,user_id) VALUES (?,?)",
                (courses["MECE 3320"], faculty_id),
            )
            db.executemany(
                """INSERT INTO course_campus_assignments
                   (course_id,user_id,campus) VALUES (?,?,?)""",
                [
                    (courses["MECE 3320"], faculty_id, campus)
                    for campus in ("Edinburg", "Brownsville")
                ],
            )
            roster_id = db.execute(
                """INSERT INTO faculty_roster
                   (program_id,legacy_name,display_name,approved_email,user_id,status)
                   VALUES (?,?,?,?,?,'active')""",
                (
                    program["id"],
                    "Assigned Faculty",
                    "Assigned Faculty",
                    "assigned.faculty@utrgv.edu",
                    faculty_id,
                ),
            ).lastrowid
            db.execute(
                """INSERT INTO faculty_roster_courses
                   (faculty_roster_id,course_id) VALUES (?,?)""",
                (roster_id, courses["MECE 3320"]),
            )
            db.executemany(
                """INSERT INTO faculty_roster_course_campuses
                   (faculty_roster_id,course_id,campus) VALUES (?,?,?)""",
                [
                    (roster_id, courses["MECE 3320"], campus)
                    for campus in ("Edinburg", "Brownsville")
                ],
            )
            term_id = db.execute(
                "SELECT id FROM academic_terms WHERE program_id=? ORDER BY sort_order DESC LIMIT 1",
                (program["id"],),
            ).fetchone()[0]
            outcome_id = db.execute(
                "SELECT id FROM outcomes WHERE program_id=? AND code='SLO1'",
                (program["id"],),
            ).fetchone()[0]
            indicator_id = db.execute(
                """SELECT id FROM performance_indicators
                   WHERE outcome_id=? AND is_active=1 ORDER BY display_order,id LIMIT 1""",
                (outcome_id,),
            ).fetchone()[0]
            rubric_id = db.execute(
                "SELECT id FROM rubrics WHERE program_id=? ORDER BY is_default DESC,id LIMIT 1",
                (program["id"],),
            ).fetchone()[0]
            level_ids = [
                row["id"]
                for row in db.execute(
                    "SELECT id FROM rubric_levels WHERE rubric_id=? ORDER BY display_order,id",
                    (rubric_id,),
                )
            ]
            db.commit()
            self.ids = {
                "organization": program["organization_id"],
                "program": program["id"],
                "owner": owner["id"],
                "faculty": faculty_id,
                "courses": courses,
                "term": term_id,
                "outcome": outcome_id,
                "indicator": indicator_id,
                "rubric": rubric_id,
                "levels": level_ids,
            }

    def tearDown(self):
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
            session["csrf_token"] = "workflow-csrf-token"

    def insert_record(
        self,
        *,
        collected_by: int,
        status: str,
        campus: str = "Edinburg",
        tool: str,
    ) -> int:
        with self.app.app_context():
            db = get_db()
            submitted_at = "2026-08-09 10:00:00" if status in {"submitted", "approved"} else None
            approved_at = "2026-08-10 11:00:00" if status == "approved" else None
            approved_by = self.ids["owner"] if status == "approved" else None
            record_id = db.execute(
                """INSERT INTO assessment_records
                   (program_id,term_id,course_id,outcome_id,indicator_id,rubric_id,
                    collected_by,approved_by,campus,method,assessment_tool,bloom_level,
                    sample_size,target,status,submitted_at,approved_at)
                   VALUES (?,?,?,?,?,?,?,?,?,'direct',?,'Analyze',10,70,?,?,?)""",
                (
                    self.ids["program"],
                    self.ids["term"],
                    self.ids["courses"]["MECE 3320"],
                    self.ids["outcome"],
                    self.ids["indicator"],
                    self.ids["rubric"],
                    collected_by,
                    approved_by,
                    campus,
                    tool,
                    status,
                    submitted_at,
                    approved_at,
                ),
            ).lastrowid
            db.executemany(
                """INSERT INTO assessment_results
                   (assessment_id,rubric_level_id,student_count) VALUES (?,?,?)""",
                [
                    (record_id, level_id, count)
                    for level_id, count in zip(
                        self.ids["levels"], (4, 4, 1, 1), strict=True
                    )
                ],
            )
            db.commit()
            return record_id

    def assessment_payload(self, *, campus: str, tool: str) -> dict[str, str]:
        payload = {
            "csrf_token": self.csrf(),
            "campus": campus,
            "term_id": str(self.ids["term"]),
            "course_id": str(self.ids["courses"]["MECE 3320"]),
            "outcome_id": str(self.ids["outcome"]),
            "indicator_id": str(self.ids["indicator"]),
            "rubric_id": str(self.ids["rubric"]),
            "method": "direct",
            "assessment_tool": tool,
            "bloom_level": "Analyze",
            "target": "70",
            "expert_percent": "40",
            "practitioner_percent": "40",
            "apprentice_percent": "10",
            "novice_percent": "10",
            "rationale": "Aligned direct evidence",
            "observations": "Interpretation after review.",
            "action_notes": "Check the next offering.",
        }
        return payload

    def record_state(self, record_id: int):
        with self.app.app_context():
            return get_db().execute(
                """SELECT status,submitted_at,approved_at,approved_by,record_version
                   FROM assessment_records WHERE id=?""",
                (record_id,),
            ).fetchone()

    def test_stale_forms_cannot_reuse_revoked_course_access(self):
        own_record = self.insert_record(
            collected_by=self.ids["faculty"],
            status="draft",
            campus="Brownsville",
            tool="Faculty Brownsville measure",
        )
        manager_record = self.insert_record(
            collected_by=self.ids["owner"],
            status="draft",
            campus="Edinburg",
            tool="Manager-owned measure",
        )
        self.as_user(self.ids["faculty"])

        own_page = self.client.get(f"/assessments/{own_record}/edit")
        self.assertIn(b"Submit for review", own_page.data)
        manager_page = self.client.get(f"/assessments/{manager_record}/edit")
        self.assertEqual(manager_page.status_code, 200)
        self.assertNotIn(b"Submit for review", manager_page.data)
        self.assertNotIn(b"Attach evidence", manager_page.data)
        self.assertEqual(
            self.client.post(
                f"/assessments/{manager_record}/status",
                data={"csrf_token": self.csrf(), "action": "submit"},
            ).status_code,
            403,
        )

        attached = self.client.post(
            f"/assessments/{own_record}/evidence",
            data={
                "csrf_token": self.csrf(),
                "title": "Faculty-owned evidence",
                "file": (io.BytesIO(b"assessment evidence"), "evidence.txt"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(attached.status_code, 302)
        with self.app.app_context():
            evidence_id = get_db().execute(
                "SELECT id FROM evidence_items WHERE assessment_id=?", (own_record,)
            ).fetchone()[0]

        with self.app.app_context():
            db = get_db()
            db.execute(
                "DELETE FROM course_assignments WHERE course_id=? AND user_id=?",
                (self.ids["courses"]["MECE 3320"], self.ids["faculty"]),
            )
            db.execute(
                """DELETE FROM course_campus_assignments
                   WHERE course_id=? AND user_id=?""",
                (self.ids["courses"]["MECE 3320"], self.ids["faculty"]),
            )
            db.commit()

        self.assertEqual(
            self.client.post(
                f"/assessments/{own_record}/status",
                data={"csrf_token": self.csrf(), "action": "submit"},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                f"/assessments/{own_record}/evidence",
                data={
                    "csrf_token": self.csrf(),
                    "title": "Stale-form evidence",
                    "source_url": "https://example.edu/evidence",
                },
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(f"/evidence/{evidence_id}/download").status_code,
            403,
        )
        with self.app.app_context():
            db = get_db()
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM evidence_items WHERE assessment_id=?",
                    (own_record,),
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                db.execute(
                    "SELECT status FROM assessment_records WHERE id=?", (own_record,)
                ).fetchone()[0],
                "draft",
            )

    def test_unassigned_utrgv_record_does_not_offer_or_accept_submission(self):
        record_id = self.insert_record(
            collected_by=self.ids["faculty"],
            status="draft",
            campus="Unassigned",
            tool="Campus unresolved",
        )
        self.as_user(self.ids["faculty"])
        page = self.client.get(f"/assessments/{record_id}/edit")
        self.assertEqual(page.status_code, 403)
        response = self.client.post(
            f"/assessments/{record_id}/status",
            data={"csrf_token": self.csrf(), "action": "submit"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.record_state(record_id)["status"], "draft")

        submitted_id = self.insert_record(
            collected_by=self.ids["faculty"],
            status="submitted",
            campus="Unassigned",
            tool="Submitted before campus migration",
        )
        self.as_user(self.ids["owner"])
        manager_page = self.client.get(f"/assessments/{submitted_id}/edit")
        self.assertIn(b"Return for revision", manager_page.data)
        self.assertNotIn(b"Approve evidence", manager_page.data)
        response = self.client.post(
            f"/assessments/{submitted_id}/status",
            data={"csrf_token": self.csrf(), "action": "approve"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.record_state(submitted_id)["status"], "submitted")

    def test_faculty_can_reopen_own_submitted_record_after_later_login(self):
        record_id = self.insert_record(
            collected_by=self.ids["faculty"],
            status="submitted",
            tool="Faculty submitted measure",
        )
        self.as_user(self.ids["faculty"])
        self.client.post("/logout", data={"csrf_token": self.csrf()})
        self.client.get("/login")
        login = self.client.post(
            "/login",
            data={
                "csrf_token": self.csrf(),
                "login": "assigned.faculty@utrgv.edu",
                "password": "faculty-password-long",
            },
        )
        self.assertEqual(login.status_code, 302)
        original = self.record_state(record_id)

        page = self.client.get(f"/assessments/{record_id}/edit")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Editing will reopen this assessment for review", page.data)
        self.assertIn(b"requires you to submit it for review again", page.data)
        self.assertIn(b"Save changes and reopen as draft", page.data)
        self.assertNotIn(b'name="admin_change_note"', page.data)

        payload = self.assessment_payload(
            campus="Brownsville",
            tool="Faculty revised submitted measure",
        )
        payload["record_version"] = str(original["record_version"])
        response = self.client.post(
            f"/assessments/{record_id}/edit",
            data=payload,
        )
        self.assertEqual(response.status_code, 302)

        state = self.record_state(record_id)
        self.assertEqual(state["status"], "draft")
        self.assertIsNone(state["submitted_at"])
        self.assertIsNone(state["approved_at"])
        self.assertIsNone(state["approved_by"])
        self.assertEqual(state["record_version"], original["record_version"] + 1)
        with self.app.app_context():
            db = get_db()
            record = db.execute(
                "SELECT collected_by,course_id,campus,assessment_tool FROM assessment_records WHERE id=?",
                (record_id,),
            ).fetchone()
            self.assertEqual(record["collected_by"], self.ids["faculty"])
            self.assertEqual(
                record["course_id"], self.ids["courses"]["MECE 3320"]
            )
            self.assertEqual(record["campus"], "Brownsville")
            self.assertEqual(
                record["assessment_tool"], "Faculty revised submitted measure"
            )
            event = db.execute(
                """SELECT user_id,details_json FROM audit_events
                   WHERE action='update' AND entity_type='assessment'
                     AND entity_id=? ORDER BY id DESC LIMIT 1""",
                (str(record_id),),
            ).fetchone()
            self.assertEqual(event["user_id"], self.ids["faculty"])
            details = json.loads(event["details_json"])
            self.assertEqual(details["previous_status"], "submitted")
            self.assertEqual(details["new_status"], "draft")
            self.assertTrue(details["review_reset"])
            self.assertFalse(details["administrative_change"])

    def test_faculty_cannot_reopen_an_approved_record(self):
        record_id = self.insert_record(
            collected_by=self.ids["faculty"],
            status="approved",
            tool="Faculty-owned approved measure",
        )
        self.as_user(self.ids["faculty"])
        page = self.client.get(f"/assessments/{record_id}/edit")
        self.assertEqual(page.status_code, 200)
        self.assertNotIn(b"Save assessment", page.data)
        self.assertNotIn(b"Save changes and reopen as draft", page.data)
        payload = self.assessment_payload(
            campus="Brownsville", tool="Unauthorized approved revision"
        )
        payload["record_version"] = str(self.record_state(record_id)["record_version"])
        self.assertEqual(
            self.client.post(f"/assessments/{record_id}/edit", data=payload).status_code,
            403,
        )
        self.assertEqual(self.record_state(record_id)["status"], "approved")

    def test_faculty_evidence_attachment_reopens_own_submitted_record(self):
        record_id = self.insert_record(
            collected_by=self.ids["faculty"],
            status="submitted",
            tool="Faculty submitted record with evidence",
        )
        self.as_user(self.ids["faculty"])
        original_version = self.record_state(record_id)["record_version"]
        page = self.client.get(f"/assessments/{record_id}/edit")
        self.assertIn(b"Review will be reopened", page.data)
        response = self.client.post(
            f"/assessments/{record_id}/evidence",
            data={
                "csrf_token": self.csrf(),
                "title": "Faculty follow-up evidence",
                "source_url": "https://example.edu/follow-up-evidence",
            },
        )
        self.assertEqual(response.status_code, 302)
        state = self.record_state(record_id)
        self.assertEqual(state["status"], "draft")
        self.assertIsNone(state["submitted_at"])
        self.assertEqual(state["record_version"], original_version + 1)
        with self.app.app_context():
            db = get_db()
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM evidence_items WHERE assessment_id=?",
                    (record_id,),
                ).fetchone()[0],
                1,
            )
            event = db.execute(
                """SELECT user_id,details_json FROM audit_events
                   WHERE action='create' AND entity_type='evidence'
                   ORDER BY id DESC LIMIT 1"""
            ).fetchone()
            self.assertEqual(event["user_id"], self.ids["faculty"])
            details = json.loads(event["details_json"])
            self.assertEqual(details["previous_status"], "submitted")
            self.assertEqual(details["new_status"], "draft")
            self.assertTrue(details["review_reset"])

    def test_faculty_reopen_preserves_optimistic_locking(self):
        record_id = self.insert_record(
            collected_by=self.ids["faculty"],
            status="submitted",
            tool="Faculty submitted before concurrent change",
        )
        self.as_user(self.ids["faculty"])
        original_version = self.record_state(record_id)["record_version"]

        with self.app.app_context():
            db = get_db()
            db.execute(
                """UPDATE assessment_records
                   SET assessment_tool='Newer stored assessment',
                       record_version=record_version+1
                   WHERE id=?""",
                (record_id,),
            )
            db.commit()

        payload = self.assessment_payload(
            campus="Brownsville", tool="Stale faculty assessment"
        )
        payload["record_version"] = str(original_version)
        response = self.client.post(
            f"/assessments/{record_id}/edit",
            data=payload,
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn(b"changed while you were editing", response.data)

        with self.app.app_context():
            db = get_db()
            record = db.execute(
                """SELECT assessment_tool,status,submitted_at,approved_at,
                          approved_by,record_version
                   FROM assessment_records WHERE id=?""",
                (record_id,),
            ).fetchone()
            self.assertEqual(record["assessment_tool"], "Newer stored assessment")
            self.assertEqual(record["status"], "submitted")
            self.assertIsNotNone(record["submitted_at"])
            self.assertIsNone(record["approved_at"])
            self.assertIsNone(record["approved_by"])
            self.assertEqual(record["record_version"], original_version + 1)
            self.assertEqual(
                db.execute(
                    """SELECT COUNT(*) FROM audit_events
                       WHERE action='update' AND entity_type='assessment'
                         AND entity_id=?""",
                    (str(record_id),),
                ).fetchone()[0],
                0,
            )

    def test_manager_material_edits_reopen_submitted_and_approved_records(self):
        self.as_user(self.ids["owner"])
        for status in ("submitted", "approved"):
            with self.subTest(status=status):
                record_id = self.insert_record(
                    collected_by=self.ids["faculty"],
                    status=status,
                    tool=f"{status.title()} record before edit",
                )
                page = self.client.get(f"/assessments/{record_id}/edit")
                self.assertIn(b"Saving changes returns this record to draft", page.data)
                edit_payload = self.assessment_payload(
                    campus="Brownsville", tool=f"{status.title()} record after edit"
                )
                edit_payload["record_version"] = str(
                    self.record_state(record_id)["record_version"]
                )
                edit_payload["admin_change_note"] = (
                    f"Administrator reopened the {status} record for correction."
                )
                response = self.client.post(
                    f"/assessments/{record_id}/edit",
                    data=edit_payload,
                )
                self.assertEqual(response.status_code, 302)
                state = self.record_state(record_id)
                self.assertEqual(state["status"], "draft")
                self.assertIsNone(state["submitted_at"])
                self.assertIsNone(state["approved_at"])
                self.assertIsNone(state["approved_by"])
                with self.app.app_context():
                    event = get_db().execute(
                        """SELECT details_json FROM audit_events
                           WHERE action='update' AND entity_type='assessment' AND entity_id=?
                           ORDER BY id DESC LIMIT 1""",
                        (str(record_id),),
                    ).fetchone()
                    details = json.loads(event["details_json"])
                    self.assertEqual(details["previous_status"], status)
                    self.assertEqual(details["new_status"], "draft")
                    self.assertTrue(details["review_reset"])

    def test_new_evidence_reopens_submitted_and_approved_records(self):
        self.as_user(self.ids["owner"])
        for status in ("submitted", "approved"):
            with self.subTest(status=status):
                record_id = self.insert_record(
                    collected_by=self.ids["faculty"],
                    status=status,
                    tool=f"{status.title()} record with new evidence",
                )
                page = self.client.get(f"/assessments/{record_id}/edit")
                self.assertIn(b"Review will be reopened", page.data)
                response = self.client.post(
                    f"/assessments/{record_id}/evidence",
                    data={
                        "csrf_token": self.csrf(),
                        "title": f"New evidence for {status}",
                        "source_url": "https://example.edu/new-evidence",
                    },
                )
                self.assertEqual(response.status_code, 302)
                state = self.record_state(record_id)
                self.assertEqual(state["status"], "draft")
                self.assertIsNone(state["submitted_at"])
                self.assertIsNone(state["approved_at"])
                self.assertIsNone(state["approved_by"])
                with self.app.app_context():
                    db = get_db()
                    self.assertEqual(
                        db.execute(
                            "SELECT COUNT(*) FROM evidence_items WHERE assessment_id=?",
                            (record_id,),
                        ).fetchone()[0],
                        1,
                    )
                    event = db.execute(
                        """SELECT details_json FROM audit_events
                           WHERE action='create' AND entity_type='evidence'
                           ORDER BY id DESC LIMIT 1"""
                    ).fetchone()
                    details = json.loads(event["details_json"])
                    self.assertEqual(details["previous_status"], status)
                    self.assertEqual(details["new_status"], "draft")
                    self.assertTrue(details["review_reset"])


if __name__ == "__main__":
    unittest.main()
