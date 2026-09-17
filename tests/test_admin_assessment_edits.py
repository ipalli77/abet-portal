from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from werkzeug.security import generate_password_hash

from abet_platform import create_app
from abet_platform.db import get_db


class AdministrativeAssessmentEditTests(unittest.TestCase):
    """Contract for traceable administrator corrections to current UTRGV data."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "administrative-edit-test-secret",
                "DATABASE": str(root / "utrgv.db"),
                "UPLOAD_FOLDER": str(root / "uploads"),
                "EDITION": "utrgv_mece",
                "PRODUCT_NAME": "UTRGV ME Accreditation Hub",
                "CUSTOMER_NAME": "UTRGV Department of Mechanical Engineering",
            }
        )
        self.client = self.app.test_client()
        self._initialize_workspace()

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
            session["csrf_token"] = "administrative-edit-csrf"

    def _initialize_workspace(self) -> None:
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
            owner_id = db.execute(
                "SELECT id FROM users WHERE email='isaac.palli@utrgv.edu'"
            ).fetchone()[0]
            admin_id = db.execute(
                "INSERT INTO users(email,full_name,password_hash) VALUES (?,?,?)",
                (
                    "admin@example.edu",
                    "ABET Administrator",
                    generate_password_hash("admin-password-long"),
                ),
            ).lastrowid
            faculty_id = db.execute(
                "INSERT INTO users(email,full_name,password_hash) VALUES (?,?,?)",
                (
                    "faculty@example.edu",
                    "Assigned Faculty",
                    generate_password_hash("faculty-password-long"),
                ),
            ).lastrowid
            db.executemany(
                "INSERT INTO memberships(user_id,organization_id,role) VALUES (?,?,?)",
                (
                    (admin_id, program["organization_id"], "admin"),
                    (faculty_id, program["organization_id"], "faculty"),
                ),
            )
            db.executemany(
                "INSERT INTO program_members(program_id,user_id,access_level) VALUES (?,?,?)",
                (
                    (program["id"], admin_id, "manager"),
                    (program["id"], faculty_id, "editor"),
                ),
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
            db.execute(
                """INSERT INTO course_campus_assignments(course_id,user_id,campus)
                   VALUES (?,?,?)""",
                (courses["MECE 3320"], faculty_id, "Edinburg"),
            )
            terms = [
                row["id"]
                for row in db.execute(
                    """SELECT id FROM academic_terms WHERE program_id=?
                       ORDER BY sort_order DESC,id DESC LIMIT 2""",
                    (program["id"],),
                )
            ]
            outcomes = db.execute(
                """SELECT id,code FROM outcomes WHERE program_id=? AND code IN ('SLO1','SLO2')
                   ORDER BY code""",
                (program["id"],),
            ).fetchall()
            outcome_ids = {row["code"]: row["id"] for row in outcomes}
            indicators = {
                code: db.execute(
                    """SELECT id FROM performance_indicators WHERE outcome_id=?
                       ORDER BY display_order,id LIMIT 1""",
                    (outcome_id,),
                ).fetchone()[0]
                for code, outcome_id in outcome_ids.items()
            }
            rubric_id = db.execute(
                """SELECT id FROM rubrics WHERE program_id=? AND name='EPAN'
                   COLLATE NOCASE""",
                (program["id"],),
            ).fetchone()[0]
            levels = db.execute(
                """SELECT id,label FROM rubric_levels WHERE rubric_id=?
                   ORDER BY display_order,id""",
                (rubric_id,),
            ).fetchall()
            db.commit()
            self.ids = {
                "organization": program["organization_id"],
                "program": program["id"],
                "owner": owner_id,
                "admin": admin_id,
                "faculty": faculty_id,
                "courses": courses,
                "terms": terms,
                "outcomes": outcome_ids,
                "indicators": indicators,
                "rubric": rubric_id,
                "levels": [(row["id"], row["label"]) for row in levels],
            }

            self.faculty_approved_record = self._insert_record(
                db,
                collected_by=faculty_id,
                status="approved",
                course_id=courses["MECE 3320"],
                tool="Faculty-approved laboratory measure",
            )
            self.imported_current_record = self._insert_imported_record(db)
            self.other_draft_record = self._insert_record(
                db,
                collected_by=owner_id,
                status="draft",
                course_id=courses["MECE 3320"],
                tool="Manager-owned draft",
            )
            self.faculty_submitted_record = self._insert_record(
                db,
                collected_by=faculty_id,
                status="submitted",
                course_id=courses["MECE 3320"],
                tool="Faculty-submitted record",
            )
            db.commit()

    def _insert_record(
        self,
        db,
        *,
        collected_by: int,
        status: str,
        course_id: int,
        tool: str,
    ) -> int:
        submitted_at = "2026-08-09 10:00:00" if status in {"submitted", "approved"} else None
        approved_at = "2026-08-10 11:00:00" if status == "approved" else None
        approved_by = self.ids["owner"] if status == "approved" else None
        record_id = db.execute(
            """INSERT INTO assessment_records
               (program_id,term_id,course_id,outcome_id,indicator_id,rubric_id,
                collected_by,approved_by,campus,method,assessment_tool,bloom_level,
                sample_size,target,rationale,observations,action_notes,status,
                submitted_at,approved_at)
               VALUES (?,?,?,?,?,?,?,?,?,'direct',?,'Analyze',10,70,?,?,?, ?,?,?)""",
            (
                self.ids["program"],
                self.ids["terms"][0],
                course_id,
                self.ids["outcomes"]["SLO1"],
                self.ids["indicators"]["SLO1"],
                self.ids["rubric"],
                collected_by,
                approved_by,
                "Edinburg",
                tool,
                "Original rationale",
                "Original observation",
                "Original action",
                status,
                submitted_at,
                approved_at,
            ),
        ).lastrowid
        counts = (3, 5, 1, 1)
        db.executemany(
            """INSERT INTO assessment_results
               (assessment_id,rubric_level_id,student_count) VALUES (?,?,?)""",
            [
                (record_id, level_id, count)
                for (level_id, _label), count in zip(self.ids["levels"], counts, strict=True)
            ],
        )
        return record_id

    def _insert_imported_record(self, db) -> int:
        record_id = db.execute(
            """INSERT INTO assessment_records
               (program_id,term_id,course_id,outcome_id,indicator_id,rubric_id,
                collected_by,approved_by,campus,method,assessment_tool,bloom_level,
                sample_size,target,rationale,observations,action_notes,status,
                submitted_at,approved_at)
               VALUES (?,?,?,?,?,?,?,?,?,'direct',?,'Analyze',10000,70,?,?,?,
                       'approved','2026-08-09 10:00:00','2026-08-10 11:00:00')""",
            (
                self.ids["program"],
                self.ids["terms"][0],
                self.ids["courses"]["MECE 3320"],
                self.ids["outcomes"]["SLO1"],
                self.ids["indicators"]["SLO1"],
                self.ids["rubric"],
                self.ids["owner"],
                self.ids["owner"],
                "Edinburg",
                "Current Edinburg laboratory measure",
                "Original source alignment",
                "Original source observation",
                "Original source action",
            ),
        ).lastrowid
        counts = (4525, 3500, 1475, 500)
        db.executemany(
            """INSERT INTO assessment_results
               (assessment_id,rubric_level_id,student_count) VALUES (?,?,?)""",
            [
                (record_id, level_id, count)
                for (level_id, _label), count in zip(self.ids["levels"], counts, strict=True)
            ],
        )
        db.execute(
            """INSERT INTO legacy_import_items
               (program_id,source_fingerprint,source_record_id,assessment_id,
                expert_percent,practitioner_percent,apprentice_percent,novice_percent)
               VALUES (?,?,?,?,45.25,35.0,14.75,5.0)""",
            (self.ids["program"], "current-edinburg-source", 1, record_id),
        )
        return record_id

    def _ordinary_payload(self, *, reason: str | None = None) -> dict[str, str]:
        payload = {
            "csrf_token": self.csrf(),
            "campus": "Brownsville",
            "term_id": str(self.ids["terms"][1]),
            "course_id": str(self.ids["courses"]["MECE 3315"]),
            "outcome_id": str(self.ids["outcomes"]["SLO2"]),
            "indicator_id": str(self.ids["indicators"]["SLO2"]),
            "rubric_id": str(self.ids["rubric"]),
            "method": "indirect",
            "assessment_tool": "Administratively corrected ordinary measure",
            "bloom_level": "Evaluate",
            "target": "72.5",
            "expert_percent": "30",
            "practitioner_percent": "50",
            "apprentice_percent": "10",
            "novice_percent": "10",
            "rationale": "Corrected alignment rationale",
            "observations": "Corrected administrator observation",
            "action_notes": "Corrected closing-the-loop action",
        }
        if reason is not None:
            payload["admin_change_note"] = reason
        return payload

    def _imported_payload(
        self,
        *,
        campus: str,
        percentages: tuple[str, str, str, str],
        tool: str,
        reason: str | None,
    ) -> dict[str, str]:
        payload = {
            "csrf_token": self.csrf(),
            "campus": campus,
            "term_id": str(self.ids["terms"][1]),
            "course_id": str(self.ids["courses"]["MECE 3315"]),
            "outcome_id": str(self.ids["outcomes"]["SLO2"]),
            "indicator_id": str(self.ids["indicators"]["SLO2"]),
            "rubric_id": str(self.ids["rubric"]),
            "method": "indirect",
            "assessment_tool": tool,
            "bloom_level": "Evaluate",
            "target": "73.5",
            "rationale": "Administrator-verified source alignment",
            "observations": "Administrator-corrected source observation",
            "action_notes": "Administrator-corrected source action",
            "expert_percent": percentages[0],
            "practitioner_percent": percentages[1],
            "apprentice_percent": percentages[2],
            "novice_percent": percentages[3],
        }
        if reason is not None:
            payload["admin_change_note"] = reason
        return payload

    def _administrative_events(self, record_id: int):
        with self.app.app_context():
            rows = get_db().execute(
                """SELECT ae.*,u.full_name FROM audit_events ae
                   LEFT JOIN users u ON u.id=ae.user_id
                   WHERE ae.action='update' AND ae.entity_type='assessment'
                     AND ae.entity_id=? ORDER BY ae.id""",
                (str(record_id),),
            ).fetchall()
            return [(row, json.loads(row["details_json"])) for row in rows]

    def _record_version(self, record_id: int) -> int:
        with self.app.app_context():
            return get_db().execute(
                "SELECT record_version FROM assessment_records WHERE id=?",
                (record_id,),
            ).fetchone()[0]

    def test_admin_can_fully_edit_a_faculty_owned_approved_record_with_visible_note(self):
        self.as_user(self.ids["admin"])
        page = self.client.get(f"/assessments/{self.faculty_approved_record}/edit")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'name="admin_change_note"', page.data)
        self.assertIn(b"Reason for administrative change", page.data)

        reason = "Corrected campus and scoring from the signed source worksheet."
        payload = self._ordinary_payload(reason=reason)
        payload["record_version"] = str(
            self._record_version(self.faculty_approved_record)
        )
        response = self.client.post(
            f"/assessments/{self.faculty_approved_record}/edit",
            data=payload,
        )
        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            record = db.execute(
                "SELECT * FROM assessment_records WHERE id=?",
                (self.faculty_approved_record,),
            ).fetchone()
            self.assertEqual(record["collected_by"], self.ids["faculty"])
            self.assertEqual(record["campus"], "Brownsville")
            self.assertEqual(record["term_id"], self.ids["terms"][1])
            self.assertEqual(record["course_id"], self.ids["courses"]["MECE 3315"])
            self.assertEqual(record["outcome_id"], self.ids["outcomes"]["SLO2"])
            self.assertEqual(record["indicator_id"], self.ids["indicators"]["SLO2"])
            self.assertEqual(record["method"], "indirect")
            self.assertEqual(record["assessment_tool"], "Administratively corrected ordinary measure")
            self.assertEqual(record["bloom_level"], "Evaluate")
            self.assertIsNone(record["sample_size"])
            self.assertEqual(record["result_basis"], "percentages")
            self.assertEqual(record["target"], 72.5)
            self.assertEqual(record["rationale"], "Corrected alignment rationale")
            self.assertEqual(record["observations"], "Corrected administrator observation")
            self.assertEqual(record["action_notes"], "Corrected closing-the-loop action")
            self.assertEqual(record["status"], "draft")
            self.assertIsNone(record["submitted_at"])
            self.assertIsNone(record["approved_at"])
            self.assertIsNone(record["approved_by"])
            percentages = [
                row["level_percent"]
                for row in db.execute(
                    """SELECT level_percent FROM assessment_results
                       WHERE assessment_id=? ORDER BY rubric_level_id""",
                    (self.faculty_approved_record,),
                )
            ]
            self.assertEqual(percentages, [30.0, 50.0, 10.0, 10.0])

        events = self._administrative_events(self.faculty_approved_record)
        self.assertEqual(len(events), 1)
        event, details = events[0]
        self.assertEqual(event["user_id"], self.ids["admin"])
        self.assertEqual(event["full_name"], "ABET Administrator")
        self.assertTrue(event["created_at"])
        self.assertTrue(details["administrative_change"])
        self.assertEqual(details["reason"], reason)
        self.assertEqual(details["previous_status"], "approved")
        self.assertEqual(details["new_status"], "draft")
        self.assertTrue(details["review_reset"])

        history = self.client.get(f"/assessments/{self.faculty_approved_record}/edit")
        self.assertIn(b"Administrative change history", history.data)
        self.assertIn(b"ABET Administrator", history.data)
        self.assertIn(reason.encode(), history.data)
        self.assertIn(event["created_at"].encode(), history.data)

        with self.app.app_context():
            revision = get_db().execute(
                """SELECT before_json,after_json FROM assessment_revisions
                   WHERE assessment_id=? ORDER BY id DESC LIMIT 1""",
                (self.faculty_approved_record,),
            ).fetchone()
            before = json.loads(revision["before_json"])
            after = json.loads(revision["after_json"])
            self.assertEqual(
                before["rubric_counts"],
                {"Expert": 3, "Practitioner": 5, "Apprentice": 1, "Novice": 1},
            )
            self.assertEqual(
                after["rubric_percentages"],
                {"expert": 30.0, "practitioner": 50.0, "apprentice": 10.0, "novice": 10.0},
            )

    def test_admin_can_edit_current_imported_epan_percentages_and_history_is_append_only(self):
        self.as_user(self.ids["admin"])
        page = self.client.get(f"/assessments/{self.imported_current_record}/edit")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'name="expert_percent"', page.data)
        self.assertIn(b'name="practitioner_percent"', page.data)
        self.assertIn(b'name="apprentice_percent"', page.data)
        self.assertIn(b'name="novice_percent"', page.data)
        self.assertIn(b'name="admin_change_note"', page.data)
        self.assertIn(b"Save assessment", page.data)

        first_reason = "Matched the current Edinburg workbook and corrected the campus."
        first_payload = self._imported_payload(
            campus="Brownsville",
            percentages=("44.125", "34.875", "16.5", "4.5"),
            tool="Administrator-corrected current measure",
            reason=first_reason,
        )
        first_payload["record_version"] = str(
            self._record_version(self.imported_current_record)
        )
        first = self.client.post(
            f"/assessments/{self.imported_current_record}/edit",
            data=first_payload,
        )
        self.assertEqual(first.status_code, 302)

        with self.app.app_context():
            db = get_db()
            record = db.execute(
                "SELECT * FROM assessment_records WHERE id=?",
                (self.imported_current_record,),
            ).fetchone()
            percentages = db.execute(
                "SELECT * FROM legacy_import_items WHERE assessment_id=?",
                (self.imported_current_record,),
            ).fetchone()
            self.assertEqual(record["campus"], "Brownsville")
            self.assertEqual(record["term_id"], self.ids["terms"][1])
            self.assertEqual(record["course_id"], self.ids["courses"]["MECE 3315"])
            self.assertEqual(record["outcome_id"], self.ids["outcomes"]["SLO2"])
            self.assertEqual(record["indicator_id"], self.ids["indicators"]["SLO2"])
            self.assertEqual(record["method"], "indirect")
            self.assertEqual(record["assessment_tool"], "Administrator-corrected current measure")
            self.assertEqual(record["bloom_level"], "Evaluate")
            self.assertEqual(record["target"], 73.5)
            self.assertEqual(record["rationale"], "Administrator-verified source alignment")
            self.assertEqual(record["observations"], "Administrator-corrected source observation")
            self.assertEqual(record["action_notes"], "Administrator-corrected source action")
            self.assertEqual(record["status"], "draft")
            self.assertAlmostEqual(percentages["expert_percent"], 44.125)
            self.assertAlmostEqual(percentages["practitioner_percent"], 34.875)
            self.assertAlmostEqual(percentages["apprentice_percent"], 16.5)
            self.assertAlmostEqual(percentages["novice_percent"], 4.5)

        # Every visible assessment field is mandatory, including the permanent
        # administrative reason shown to an owner or administrator.
        second_reason = "Rechecked the current source distribution and campus."
        second_payload = self._imported_payload(
            campus="Edinburg",
            percentages=("50.25", "28.75", "15.5", "5.5"),
            tool="Second administrator correction",
            reason=second_reason,
        )
        second_payload["record_version"] = str(
            self._record_version(self.imported_current_record)
        )
        second = self.client.post(
            f"/assessments/{self.imported_current_record}/edit",
            data=second_payload,
        )
        self.assertEqual(second.status_code, 302)

        events = self._administrative_events(self.imported_current_record)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0][1]["reason"], first_reason)
        self.assertEqual(events[1][1]["reason"], second_reason)
        self.assertTrue(all(details["administrative_change"] for _row, details in events))
        self.assertTrue(all(row["full_name"] == "ABET Administrator" for row, _details in events))

        with self.app.app_context():
            final = get_db().execute(
                """SELECT ar.campus,ar.assessment_tool,li.expert_percent,
                          li.practitioner_percent,li.apprentice_percent,li.novice_percent
                   FROM assessment_records ar
                   JOIN legacy_import_items li ON li.assessment_id=ar.id
                   WHERE ar.id=?""",
                (self.imported_current_record,),
            ).fetchone()
            self.assertEqual(final["campus"], "Edinburg")
            self.assertEqual(final["assessment_tool"], "Second administrator correction")
            self.assertAlmostEqual(final["expert_percent"], 50.25)
            self.assertAlmostEqual(final["practitioner_percent"], 28.75)
            self.assertAlmostEqual(final["apprentice_percent"], 15.5)
            self.assertAlmostEqual(final["novice_percent"], 5.5)

        history = self.client.get(f"/assessments/{self.imported_current_record}/edit")
        self.assertIn(b"Administrative change history", history.data)
        self.assertIn(first_reason.encode(), history.data)
        for event, _details in events:
            self.assertIn(event["created_at"].encode(), history.data)

    def test_faculty_cannot_edit_imported_or_other_owners_records(self):
        self.as_user(self.ids["faculty"])

        imported_page = self.client.get(f"/assessments/{self.imported_current_record}/edit")
        self.assertEqual(imported_page.status_code, 200)
        self.assertNotIn(b'name="admin_change_note"', imported_page.data)
        self.assertNotIn(b"Save assessment", imported_page.data)
        crafted = self._imported_payload(
            campus="Brownsville",
            percentages=("25", "25", "25", "25"),
            tool="Unauthorized imported edit",
            reason="Pretend administrator override",
        )
        crafted["admin_override"] = "1"
        response = self.client.post(
            f"/assessments/{self.imported_current_record}/edit",
            data=crafted,
        )
        self.assertEqual(response.status_code, 403)

        self.assertEqual(
            self.client.post(
                f"/assessments/{self.other_draft_record}/edit",
                data=self._ordinary_payload(reason="Unauthorized other-owner edit"),
            ).status_code,
            403,
        )
        with self.app.app_context():
            db = get_db()
            imported = db.execute(
                """SELECT ar.campus,ar.assessment_tool,li.expert_percent
                   FROM assessment_records ar
                   JOIN legacy_import_items li ON li.assessment_id=ar.id
                   WHERE ar.id=?""",
                (self.imported_current_record,),
            ).fetchone()
            self.assertEqual(tuple(imported), ("Edinburg", "Current Edinburg laboratory measure", 45.25))
            self.assertEqual(
                db.execute(
                    """SELECT COUNT(*) FROM audit_events
                       WHERE action='update' AND entity_type='assessment'"""
                ).fetchone()[0],
                0,
            )

    def test_primary_navigation_has_no_legacy_archive_item(self):
        self.as_user(self.ids["admin"])
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertNotIn(b"Legacy archive", page.data)
        self.assertNotIn(b'href="/utrgv/legacy"', page.data)

    def test_stale_administrator_edit_is_rejected_without_overwriting_newer_data(self):
        self.as_user(self.ids["admin"])
        page = self.client.get(f"/assessments/{self.faculty_approved_record}/edit")
        self.assertEqual(page.status_code, 200)
        original_version = self._record_version(self.faculty_approved_record)
        self.assertIn(b'name="record_version"', page.data)
        self.assertIn(f'value="{original_version}"'.encode(), page.data)

        with self.app.app_context():
            db = get_db()
            db.execute(
                """UPDATE assessment_records
                   SET assessment_tool='Newer administrator data',
                       record_version=record_version+1
                   WHERE id=?""",
                (self.faculty_approved_record,),
            )
            db.commit()

        stale_payload = self._ordinary_payload(
            reason="This stale browser tab must not overwrite newer data."
        )
        stale_payload["record_version"] = str(original_version)
        response = self.client.post(
            f"/assessments/{self.faculty_approved_record}/edit",
            data=stale_payload,
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn(
            b"This assessment changed while you were editing it. Refresh and try again.",
            response.data,
        )

        with self.app.app_context():
            db = get_db()
            record = db.execute(
                "SELECT assessment_tool,record_version,status FROM assessment_records WHERE id=?",
                (self.faculty_approved_record,),
            ).fetchone()
            self.assertEqual(record["assessment_tool"], "Newer administrator data")
            self.assertEqual(record["record_version"], original_version + 1)
            self.assertEqual(record["status"], "approved")
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM assessment_revisions WHERE assessment_id=?",
                    (self.faculty_approved_record,),
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                db.execute(
                    """SELECT COUNT(*) FROM audit_events
                       WHERE action='update' AND entity_type='assessment'
                         AND entity_id=?""",
                    (str(self.faculty_approved_record),),
                ).fetchone()[0],
                0,
            )

    def test_latest_administrative_note_is_visible_in_report_and_csv_export(self):
        older_note = "Initial administrator correction superseded by later verification."
        latest_note = "Verified against the signed Edinburg assessment worksheet."
        with self.app.app_context():
            db = get_db()
            db.executemany(
                """INSERT INTO assessment_revisions
                   (program_id,assessment_id,changed_by,changed_by_name,change_note,
                    before_json,after_json,created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    (
                        self.ids["program"],
                        self.faculty_approved_record,
                        self.ids["admin"],
                        "ABET Administrator",
                        older_note,
                        "{}",
                        "{}",
                        "2026-08-10 08:00:00",
                    ),
                    (
                        self.ids["program"],
                        self.faculty_approved_record,
                        self.ids["admin"],
                        "ABET Administrator",
                        latest_note,
                        "{}",
                        "{}",
                        "2026-08-11 09:30:00",
                    ),
                ),
            )
            db.commit()

        self.as_user(self.ids["admin"])
        report = self.client.get("/report")
        self.assertEqual(report.status_code, 200)
        self.assertIn(b"Administrator changed:", report.data)
        self.assertIn(latest_note.encode(), report.data)
        self.assertIn(b"ABET Administrator", report.data)
        self.assertIn(b"2026-08-11 09:30:00", report.data)
        self.assertNotIn(older_note.encode(), report.data)

        exported = self.client.get("/export/assessments.csv")
        self.assertEqual(exported.status_code, 200)
        rows = list(csv.DictReader(io.StringIO(exported.text)))
        row = next(
            item
            for item in rows
            if item["assessment_tool"] == "Faculty-approved laboratory measure"
        )
        self.assertEqual(row["administrator_changed"], "yes")
        self.assertEqual(row["administrator_change_note"], latest_note)
        self.assertEqual(row["administrator_changed_by"], "ABET Administrator")
        self.assertEqual(row["administrator_changed_at"], "2026-08-11 09:30:00")

        unchanged = next(
            item for item in rows if item["assessment_tool"] == "Manager-owned draft"
        )
        self.assertEqual(unchanged["administrator_changed"], "no")
        self.assertEqual(unchanged["administrator_change_note"], "")
        self.assertEqual(unchanged["administrator_changed_by"], "")
        self.assertEqual(unchanged["administrator_changed_at"], "")


if __name__ == "__main__":
    unittest.main()
