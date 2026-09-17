from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from werkzeug.security import generate_password_hash

from abet_platform import create_app
from abet_platform.db import get_db


class BulkApprovalTests(unittest.TestCase):
    """Authorization, scoping, validation, and audit contracts for bulk approval."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "bulk-approval-test-secret",
                "DATABASE": str(root / "utrgv.db"),
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
        self._build_fixture()

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
            session["csrf_token"] = "bulk-approval-csrf"

    def _build_fixture(self) -> None:
        with self.app.app_context():
            db = get_db()
            program = db.execute(
                "SELECT * FROM programs WHERE code='BSME'"
            ).fetchone()
            owner_id = db.execute(
                "SELECT id FROM users WHERE email='isaac.palli@utrgv.edu'"
            ).fetchone()[0]

            users: dict[str, int] = {"owner": owner_id}
            for role in ("admin", "coordinator", "faculty"):
                users[role] = db.execute(
                    "INSERT INTO users(email,full_name,password_hash) VALUES (?,?,?)",
                    (
                        f"{role}@example.edu",
                        role.title(),
                        generate_password_hash(f"{role}-password-long"),
                    ),
                ).lastrowid
                db.execute(
                    "INSERT INTO memberships(user_id,organization_id,role) VALUES (?,?,?)",
                    (users[role], program["organization_id"], role),
                )
                db.execute(
                    "INSERT INTO program_members(program_id,user_id,access_level) VALUES (?,?,?)",
                    (
                        program["id"],
                        users[role],
                        "manager" if role in {"admin", "coordinator"} else "editor",
                    ),
                )

            courses = {
                row["code"]: row["id"]
                for row in db.execute(
                    "SELECT id,code FROM courses WHERE program_id=?",
                    (program["id"],),
                )
            }
            terms = [
                row["id"]
                for row in db.execute(
                    """SELECT id FROM academic_terms WHERE program_id=?
                       ORDER BY sort_order DESC,id DESC LIMIT 2""",
                    (program["id"],),
                )
            ]
            outcomes = {
                row["code"]: row["id"]
                for row in db.execute(
                    """SELECT id,code FROM outcomes WHERE program_id=?
                       AND code IN ('SLO1','SLO2')""",
                    (program["id"],),
                )
            }
            indicators = {
                code: db.execute(
                    """SELECT id FROM performance_indicators WHERE outcome_id=?
                       ORDER BY display_order,id LIMIT 1""",
                    (outcome_id,),
                ).fetchone()[0]
                for code, outcome_id in outcomes.items()
            }
            rubric_id = db.execute(
                """SELECT id FROM rubrics WHERE program_id=?
                   AND name='EPAN' COLLATE NOCASE""",
                (program["id"],),
            ).fetchone()[0]
            levels = [
                row["id"]
                for row in db.execute(
                    """SELECT id FROM rubric_levels WHERE rubric_id=?
                       ORDER BY display_order,id""",
                    (rubric_id,),
                )
            ]

            # Additional scopes make crafted cross-program and cross-tenant IDs
            # concrete without granting the current owner access to them.
            sibling_program = db.execute(
                """INSERT INTO programs(organization_id,code,name)
                   VALUES (?, 'OTHER', 'Other program')""",
                (program["organization_id"],),
            ).lastrowid
            sibling_course = db.execute(
                """INSERT INTO courses(program_id,code,name)
                   VALUES (?, 'OTHER 1000', 'Other-program course')""",
                (sibling_program,),
            ).lastrowid
            foreign_org = db.execute(
                "INSERT INTO organizations(name,slug) VALUES ('Other University','other-university')"
            ).lastrowid
            foreign_program = db.execute(
                """INSERT INTO programs(organization_id,code,name)
                   VALUES (?, 'FOREIGN', 'Foreign program')""",
                (foreign_org,),
            ).lastrowid
            foreign_course = db.execute(
                """INSERT INTO courses(program_id,code,name)
                   VALUES (?, 'FOREIGN 1000', 'Foreign course')""",
                (foreign_program,),
            ).lastrowid
            db.commit()

            self.ids = {
                "organization": program["organization_id"],
                "program": program["id"],
                **users,
                "courses": courses,
                "terms": terms,
                "outcomes": outcomes,
                "indicators": indicators,
                "rubric": rubric_id,
                "levels": levels,
                "sibling_program": sibling_program,
                "sibling_course": sibling_course,
                "foreign_program": foreign_program,
                "foreign_course": foreign_course,
            }

    def insert_record(
        self,
        *,
        status: str = "draft",
        course_id: int | None = None,
        campus: str = "Edinburg",
        term_id: int | None = None,
        outcome_code: str = "SLO1",
        complete: bool = True,
        program_id: int | None = None,
        tool: str | None = None,
    ) -> int:
        program_id = program_id or self.ids["program"]
        course_id = course_id or self.ids["courses"]["MECE 3320"]
        term_id = term_id or self.ids["terms"][0]
        submitted_at = (
            "2026-08-15 10:00:00" if status in {"submitted", "approved"} else None
        )
        approved_at = "2026-08-15 11:00:00" if status == "approved" else None
        approved_by = self.ids["owner"] if status == "approved" else None
        with self.app.app_context():
            db = get_db()
            record_id = db.execute(
                """INSERT INTO assessment_records
                   (program_id,term_id,course_id,outcome_id,indicator_id,rubric_id,
                    collected_by,approved_by,campus,method,assessment_tool,bloom_level,
                    sample_size,result_basis,target,rationale,observations,action_notes,
                    status,submitted_at,approved_at)
                   VALUES (?,?,?,?,?,?,?,?,?,'direct',?,'Analyze',NULL,'percentages',
                           70,?,?,?, ?,?,?)""",
                (
                    program_id,
                    term_id,
                    course_id,
                    self.ids["outcomes"][outcome_code],
                    self.ids["indicators"][outcome_code],
                    self.ids["rubric"],
                    self.ids["faculty"],
                    approved_by,
                    campus,
                    tool or f"{status.title()} {course_id} assessment",
                    "Required rationale",
                    "Required observations",
                    "Required action" if complete else "",
                    status,
                    submitted_at,
                    approved_at,
                ),
            ).lastrowid
            db.executemany(
                """INSERT INTO assessment_results
                   (assessment_id,rubric_level_id,student_count,level_percent)
                   VALUES (?,?,0,?)""",
                [
                    (record_id, level_id, percent)
                    for level_id, percent in zip(
                        self.ids["levels"], (40.0, 40.0, 10.0, 10.0), strict=True
                    )
                ],
            )
            db.commit()
            return record_id

    def post_bulk(
        self,
        mode: str,
        *,
        records: list[int] | None = None,
        courses: list[int] | None = None,
        csrf_token: str | None = None,
        **filters: str | int,
    ):
        data: dict[str, object] = {
            "csrf_token": self.csrf() if csrf_token is None else csrf_token,
            "selection_mode": mode,
        }
        if records is not None:
            data["record_ids"] = [str(value) for value in records]
        if courses is not None:
            data["course_ids"] = [str(value) for value in courses]
        for name, value in filters.items():
            data[f"filter_{name}"] = str(value)
        return self.client.post("/assessments/bulk-approve", data=data)

    def states(self, *record_ids: int) -> dict[int, dict]:
        placeholders = ",".join("?" for _ in record_ids)
        with self.app.app_context():
            rows = get_db().execute(
                f"""SELECT id,status,submitted_at,approved_at,approved_by,record_version
                    FROM assessment_records WHERE id IN ({placeholders})""",
                record_ids,
            ).fetchall()
            return {row["id"]: dict(row) for row in rows}

    def audit_events(self) -> list[dict]:
        with self.app.app_context():
            rows = get_db().execute(
                """SELECT organization_id,user_id,action,entity_type,entity_id,details_json
                   FROM audit_events
                   WHERE action IN ('approve','bulk_approve') ORDER BY id"""
            ).fetchall()
            return [dict(row) for row in rows]

    def test_owner_approves_selected_draft_and_submitted_records_with_audit(self) -> None:
        draft = self.insert_record(status="draft", tool="Selected draft")
        submitted = self.insert_record(status="submitted", tool="Selected submission")
        unselected = self.insert_record(status="draft", tool="Unselected draft")
        before = self.states(draft, submitted, unselected)
        self.as_user(self.ids["owner"])

        response = self.post_bulk("records", records=[draft, submitted])
        self.assertEqual(response.status_code, 302)

        after = self.states(draft, submitted, unselected)
        for record_id in (draft, submitted):
            with self.subTest(record_id=record_id):
                self.assertEqual(after[record_id]["status"], "approved")
                self.assertIsNotNone(after[record_id]["submitted_at"])
                self.assertIsNotNone(after[record_id]["approved_at"])
                self.assertEqual(after[record_id]["approved_by"], self.ids["owner"])
                self.assertEqual(
                    after[record_id]["record_version"],
                    before[record_id]["record_version"] + 1,
                )
        self.assertEqual(after[unselected], before[unselected])

        events = self.audit_events()
        approvals = [event for event in events if event["action"] == "approve"]
        batches = [event for event in events if event["action"] == "bulk_approve"]
        self.assertEqual(len(approvals), 2)
        self.assertEqual(len(batches), 1)
        batch_id = batches[0]["entity_id"]
        for event in approvals:
            details = json.loads(event["details_json"])
            self.assertEqual(event["organization_id"], self.ids["organization"])
            self.assertEqual(event["user_id"], self.ids["owner"])
            self.assertEqual(event["entity_type"], "assessment")
            self.assertIn(int(event["entity_id"]), {draft, submitted})
            self.assertIn(details["from"], {"draft", "submitted"})
            self.assertEqual(details["to"], "approved")
            self.assertTrue(details["bulk"])
            self.assertEqual(details["batch_id"], batch_id)
            self.assertEqual(details["selection_mode"], "records")

        batch = json.loads(batches[0]["details_json"])
        self.assertEqual(batches[0]["user_id"], self.ids["owner"])
        self.assertEqual(batches[0]["entity_type"], "assessment_batch")
        self.assertEqual(batch["selection_mode"], "records")
        self.assertEqual(batch["record_count"], 2)
        self.assertEqual(set(batch["record_ids"]), {draft, submitted})
        self.assertEqual(batch["from_status_counts"], {"draft": 1, "submitted": 1})

    def test_admin_can_approve_and_an_approved_record_cannot_be_approved_twice(self) -> None:
        draft = self.insert_record(status="draft", tool="Admin direct approval")
        self.as_user(self.ids["admin"])
        before = self.states(draft)[draft]

        first = self.post_bulk("records", records=[draft])
        self.assertEqual(first.status_code, 302)
        approved = self.states(draft)[draft]
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(approved["approved_by"], self.ids["admin"])
        self.assertEqual(approved["record_version"], before["record_version"] + 1)
        event_count = len(self.audit_events())

        # Explicit record mode is intentionally strict: an old page cannot
        # reapprove a record that another administrator already approved.
        repeated = self.post_bulk("records", records=[draft])
        self.assertEqual(repeated.status_code, 400)
        self.assertEqual(self.states(draft)[draft], approved)
        self.assertEqual(len(self.audit_events()), event_count)

    def test_course_selection_honors_visible_filters_and_ignores_other_statuses(self) -> None:
        selected_course = self.ids["courses"]["MECE 3320"]
        other_course = self.ids["courses"]["MECE 3315"]
        selected = self.insert_record(
            status="draft", course_id=selected_course, campus="Edinburg"
        )
        wrong_campus = self.insert_record(
            status="draft", course_id=selected_course, campus="Brownsville"
        )
        submitted_hidden_by_status = self.insert_record(
            status="submitted", course_id=selected_course, campus="Edinburg"
        )
        already_approved = self.insert_record(
            status="approved", course_id=selected_course, campus="Edinburg"
        )
        returned = self.insert_record(
            status="returned", course_id=selected_course, campus="Edinburg"
        )
        other = self.insert_record(
            status="draft", course_id=other_course, campus="Edinburg"
        )
        record_ids = (
            selected,
            wrong_campus,
            submitted_hidden_by_status,
            already_approved,
            returned,
            other,
        )
        before = self.states(*record_ids)
        self.as_user(self.ids["owner"])

        response = self.post_bulk(
            "courses",
            courses=[selected_course],
            campus="Edinburg",
            status="draft",
        )
        self.assertEqual(response.status_code, 302)
        after = self.states(*record_ids)
        self.assertEqual(after[selected]["status"], "approved")
        for record_id in record_ids[1:]:
            with self.subTest(record_id=record_id):
                self.assertEqual(after[record_id], before[record_id])
        self.assertEqual(
            len([event for event in self.audit_events() if event["action"] == "approve"]),
            1,
        )

    def test_select_all_approves_only_records_visible_through_every_filter(self) -> None:
        course = self.ids["courses"]["MECE 3320"]
        other_course = self.ids["courses"]["MECE 3315"]
        term = self.ids["terms"][0]
        matching_draft = self.insert_record(
            status="draft", course_id=course, term_id=term, outcome_code="SLO1"
        )
        matching_submitted = self.insert_record(
            status="submitted", course_id=course, term_id=term, outcome_code="SLO1"
        )
        wrong_campus = self.insert_record(
            status="draft", course_id=course, campus="Brownsville", term_id=term
        )
        wrong_term = self.insert_record(
            status="draft", course_id=course, term_id=self.ids["terms"][1]
        )
        wrong_course = self.insert_record(
            status="draft", course_id=other_course, term_id=term
        )
        wrong_outcome = self.insert_record(
            status="draft", course_id=course, term_id=term, outcome_code="SLO2"
        )
        approved = self.insert_record(
            status="approved", course_id=course, term_id=term, outcome_code="SLO1"
        )
        returned = self.insert_record(
            status="returned", course_id=course, term_id=term, outcome_code="SLO1"
        )
        record_ids = (
            matching_draft,
            matching_submitted,
            wrong_campus,
            wrong_term,
            wrong_course,
            wrong_outcome,
            approved,
            returned,
        )
        before = self.states(*record_ids)
        self.as_user(self.ids["owner"])

        response = self.post_bulk(
            "all",
            campus="Edinburg",
            term_id=term,
            course_id=course,
            outcome_id=self.ids["outcomes"]["SLO1"],
        )
        self.assertEqual(response.status_code, 302)
        after = self.states(*record_ids)
        self.assertEqual(after[matching_draft]["status"], "approved")
        self.assertEqual(after[matching_submitted]["status"], "approved")
        for record_id in record_ids[2:]:
            with self.subTest(record_id=record_id):
                self.assertEqual(after[record_id], before[record_id])

    def test_incomplete_candidate_makes_every_selection_mode_atomic(self) -> None:
        course = self.ids["courses"]["MECE 3320"]
        valid = self.insert_record(status="draft", course_id=course, complete=True)
        incomplete = self.insert_record(
            status="draft", course_id=course, complete=False, tool="Incomplete record"
        )
        before = self.states(valid, incomplete)
        self.as_user(self.ids["owner"])

        requests = (
            ("records", {"records": [valid, incomplete]}),
            ("courses", {"courses": [course]}),
            ("all", {"course_id": course}),
        )
        for mode, kwargs in requests:
            with self.subTest(mode=mode):
                response = self.post_bulk(mode, **kwargs)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(self.states(valid, incomplete), before)
                self.assertEqual(self.audit_events(), [])

    def test_unassigned_record_is_visible_but_blocks_the_whole_batch(self) -> None:
        course = self.ids["courses"]["MECE 3320"]
        valid = self.insert_record(
            status="draft", course_id=course, campus="Edinburg"
        )
        unassigned = self.insert_record(
            status="draft", course_id=course, campus="Unassigned"
        )
        before = self.states(valid, unassigned)
        self.as_user(self.ids["owner"])

        page = self.client.get("/assessments")
        self.assertIn(f'name="record_ids" value="{valid}"'.encode(), page.data)
        self.assertIn(f'name="record_ids" value="{unassigned}"'.encode(), page.data)

        response = self.post_bulk("all", course_id=course)
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Assign this record to Edinburg or Brownsville", response.data)
        self.assertEqual(self.states(valid, unassigned), before)
        self.assertEqual(self.audit_events(), [])

    def test_crafted_record_course_and_filter_ids_cannot_cross_scope(self) -> None:
        own_record = self.insert_record(status="draft", tool="Own valid record")
        sibling_record = self.insert_record(
            status="draft",
            program_id=self.ids["sibling_program"],
            course_id=self.ids["sibling_course"],
            tool="Sibling-program record",
        )
        foreign_record = self.insert_record(
            status="draft",
            program_id=self.ids["foreign_program"],
            course_id=self.ids["foreign_course"],
            tool="Foreign-tenant record",
        )
        poisoned_course_record = self.insert_record(
            status="draft",
            program_id=self.ids["program"],
            course_id=self.ids["sibling_course"],
            tool="Current-program record with a foreign course",
        )
        record_ids = (
            own_record,
            sibling_record,
            foreign_record,
            poisoned_course_record,
        )
        initial = self.states(*record_ids)
        self.as_user(self.ids["owner"])

        attacks = (
            ("records", {"records": [own_record, sibling_record]}, 403),
            ("records", {"records": [own_record, foreign_record]}, 403),
            ("records", {"records": [own_record, poisoned_course_record]}, 403),
            (
                "courses",
                {
                    "courses": [
                        self.ids["courses"]["MECE 3320"],
                        self.ids["sibling_course"],
                    ]
                },
                403,
            ),
            (
                "all",
                {"course_id": self.ids["sibling_course"]},
                400,
            ),
            ("records", {"records": [own_record, 999_999_999]}, 403),
        )
        for mode, kwargs, expected_status in attacks:
            with self.subTest(mode=mode, kwargs=kwargs):
                response = self.post_bulk(mode, **kwargs)
                self.assertEqual(response.status_code, expected_status)
                self.assertEqual(self.states(*record_ids), initial)
                self.assertEqual(self.audit_events(), [])

    def test_faculty_coordinator_csrf_and_non_utrgv_requests_are_denied(self) -> None:
        draft = self.insert_record(status="draft", tool="Protected draft")
        before = self.states(draft)[draft]

        for role in ("faculty", "coordinator"):
            with self.subTest(role=role):
                self.as_user(self.ids[role])
                response = self.post_bulk("records", records=[draft])
                self.assertEqual(response.status_code, 403)
                self.assertEqual(self.states(draft)[draft], before)

        self.as_user(self.ids["owner"])
        response = self.client.post(
            "/assessments/bulk-approve",
            data={"selection_mode": "records", "record_ids": str(draft)},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.states(draft)[draft], before)

        self.app.config["EDITION"] = "generic"
        response = self.post_bulk("records", records=[draft])
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.states(draft)[draft], before)
        self.assertEqual(self.audit_events(), [])

    def test_bulk_controls_are_visible_only_to_owner_and_admin(self) -> None:
        course = self.ids["courses"]["MECE 3320"]
        draft = self.insert_record(status="draft", course_id=course)
        submitted = self.insert_record(status="submitted", course_id=course)
        approved = self.insert_record(status="approved", course_id=course)
        returned = self.insert_record(status="returned", course_id=course)

        for role in ("owner", "admin"):
            with self.subTest(role=role):
                self.as_user(self.ids[role])
                page = self.client.get("/assessments")
                self.assertEqual(page.status_code, 200)
                self.assertIn(b'action="/assessments/bulk-approve"', page.data)
                for mode in ("records", "courses", "all"):
                    self.assertIn(
                        f'name="selection_mode" value="{mode}"'.encode(), page.data
                    )
                self.assertIn(
                    f'name="record_ids" value="{draft}"'.encode(), page.data
                )
                self.assertIn(
                    f'name="record_ids" value="{submitted}"'.encode(), page.data
                )
                self.assertNotIn(
                    f'name="record_ids" value="{approved}"'.encode(), page.data
                )
                self.assertNotIn(
                    f'name="record_ids" value="{returned}"'.encode(), page.data
                )
                self.assertIn(
                    f'name="course_ids" value="{course}"'.encode(), page.data
                )
                self.assertIn(b"Select all visible", page.data)
                self.assertIn(b"current filters", page.data)
                self.assertIn(b"submitted and approved in the same audited action", page.data)

        for role in ("faculty", "coordinator"):
            with self.subTest(role=role):
                self.as_user(self.ids[role])
                page = self.client.get("/assessments")
                self.assertEqual(page.status_code, 200)
                self.assertNotIn(b'action="/assessments/bulk-approve"', page.data)
                self.assertNotIn(b'name="selection_mode"', page.data)
                self.assertNotIn(b'name="record_ids"', page.data)
                self.assertNotIn(b'name="course_ids"', page.data)

        self.as_user(self.ids["owner"])
        filtered = self.client.get(
            "/assessments",
            query_string={
                "status": "draft",
                "campus": "Edinburg",
                "term_id": self.ids["terms"][0],
                "course_id": course,
                "outcome_id": self.ids["outcomes"]["SLO1"],
            },
        )
        for name, value in (
            ("filter_status", "draft"),
            ("filter_campus", "Edinburg"),
            ("filter_term_id", self.ids["terms"][0]),
            ("filter_course_id", course),
            ("filter_outcome_id", self.ids["outcomes"]["SLO1"]),
        ):
            self.assertIn(
                f'name="{name}" value="{value}"'.encode(), filtered.data
            )


if __name__ == "__main__":
    unittest.main()
