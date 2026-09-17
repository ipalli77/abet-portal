from __future__ import annotations

import csv
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import abet_platform.routes as routes
from abet_platform import create_app
from abet_platform.db import get_db


OWNER_EMAIL = "isaac.palli@utrgv.edu"


class FacultyCourseIsolationTests(unittest.TestCase):
    """UTRGV faculty must never receive another course's program data."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.upload_folder = root / "uploads"
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "faculty-course-isolation-secret",
                "DATABASE": str(root / "utrgv.db"),
                "UPLOAD_FOLDER": str(self.upload_folder),
                "EDITION": "utrgv_mece",
                "PRODUCT_NAME": "UTRGV ME Accreditation Hub",
                "CUSTOMER_NAME": "UTRGV Department of Mechanical Engineering",
            }
        )
        self.client = self.app.test_client()
        self._setup_owner()

        with self.app.app_context():
            db = get_db()
            program = db.execute("SELECT * FROM programs WHERE code='BSME'").fetchone()
            owner = db.execute(
                "SELECT * FROM users WHERE email=?", (OWNER_EMAIL,)
            ).fetchone()
            self.ids: dict[str, object] = {
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

        faculty_a = self._activate("Nadim Zgheib", "nadim.scope")
        faculty_b = self._activate("Robert Jones", "robert.scope")
        self.ids["faculty_a"] = faculty_a
        self.ids["faculty_b"] = faculty_b
        self.course_a = self.ids["courses"]["MECE 3315"]
        self.course_b = self.ids["courses"]["MECE 2340"]
        self._seed_scoped_data()

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
            session["csrf_token"] = "faculty-course-isolation-csrf"

    def _setup_owner(self) -> None:
        self.client.get("/setup")
        created = self.client.post(
            "/setup",
            data={
                "csrf_token": self.csrf(),
                "full_name": "Isaac Choutapalli",
                "email": OWNER_EMAIL,
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

    def _activate(self, display_name: str, username: str) -> int:
        with self.app.app_context():
            roster_id = get_db().execute(
                "SELECT id FROM faculty_roster WHERE display_name=?",
                (display_name,),
            ).fetchone()[0]
        activated = self.client.post(
            f"/utrgv/faculty/{roster_id}/activate",
            data={
                "csrf_token": self.csrf(),
                "username": username,
                "temporary_password": "temporary-password",
            },
        )
        self.assertEqual(activated.status_code, 302)
        with self.app.app_context():
            db = get_db()
            user_id = db.execute(
                "SELECT user_id FROM faculty_roster WHERE id=?", (roster_id,)
            ).fetchone()[0]
            db.execute(
                "UPDATE users SET must_change_password=0 WHERE id=?", (user_id,)
            )
            db.commit()
            return user_id

    def _seed_scoped_data(self) -> None:
        with self.app.app_context():
            db = get_db()
            term_id = db.execute(
                "SELECT id FROM academic_terms WHERE program_id=? ORDER BY id LIMIT 1",
                (self.ids["program"],),
            ).fetchone()[0]
            outcome_id = db.execute(
                "SELECT id FROM outcomes WHERE program_id=? ORDER BY id LIMIT 1",
                (self.ids["program"],),
            ).fetchone()[0]
            indicator_id = db.execute(
                "SELECT id FROM performance_indicators WHERE outcome_id=? ORDER BY id LIMIT 1",
                (outcome_id,),
            ).fetchone()[0]
            rubric_id = db.execute(
                "SELECT id FROM rubrics WHERE program_id=? AND name='EPAN'",
                (self.ids["program"],),
            ).fetchone()[0]
            levels = db.execute(
                "SELECT id,label FROM rubric_levels WHERE rubric_id=? ORDER BY display_order,id",
                (rubric_id,),
            ).fetchall()
            self.dimensions = {
                "term": term_id,
                "outcome": outcome_id,
                "indicator": indicator_id,
                "rubric": rubric_id,
            }

            records: dict[str, int] = {}
            specifications = (
                (
                    "a_edinburg",
                    self.course_a,
                    self.ids["faculty_a"],
                    "Edinburg",
                    "A_SCOPE_EDINBURG_TOOL",
                    (22.0, 60.0, 10.0, 8.0),
                ),
                (
                    "a_brownsville",
                    self.course_a,
                    self.ids["faculty_a"],
                    "Brownsville",
                    "A_SCOPE_BROWNSVILLE_TOOL",
                    (24.0, 60.0, 9.0, 7.0),
                ),
                (
                    "b_edinburg",
                    self.course_b,
                    self.ids["faculty_b"],
                    "Edinburg",
                    "B_SECRET_EDINBURG_TOOL",
                    (10.0, 42.0, 28.0, 20.0),
                ),
                (
                    "b_brownsville",
                    self.course_b,
                    self.ids["faculty_b"],
                    "Brownsville",
                    "B_SECRET_BROWNSVILLE_TOOL",
                    (12.0, 42.0, 26.0, 20.0),
                ),
                (
                    "b_unassigned",
                    self.course_b,
                    self.ids["faculty_b"],
                    "Unassigned",
                    "B_SECRET_UNASSIGNED_TOOL",
                    (14.0, 42.0, 24.0, 20.0),
                ),
            )
            for key, course_id, collector_id, campus, tool, percentages in specifications:
                record_id = db.execute(
                    """INSERT INTO assessment_records
                       (program_id,term_id,course_id,outcome_id,indicator_id,
                        rubric_id,collected_by,approved_by,campus,method,
                        assessment_tool,bloom_level,result_basis,target,rationale,
                        observations,action_notes,status,submitted_at,approved_at)
                       VALUES (?,?,?,?,?,?,?,?,?,'direct',?,'Analyze','percentages',
                               70,?,?,?,'approved',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)""",
                    (
                        self.ids["program"],
                        term_id,
                        course_id,
                        outcome_id,
                        indicator_id,
                        rubric_id,
                        collector_id,
                        self.ids["owner"],
                        campus,
                        tool,
                        f"RATIONALE_{key.upper()}",
                        f"OBSERVATION_{key.upper()}",
                        f"ACTION_NOTE_{key.upper()}",
                    ),
                ).lastrowid
                records[key] = record_id
                db.executemany(
                    """INSERT INTO assessment_results
                       (assessment_id,rubric_level_id,student_count,level_percent)
                       VALUES (?,?,?,?)""",
                    [
                        (record_id, level["id"], int(percent), percent)
                        for level, percent in zip(levels, percentages, strict=True)
                    ],
                )
            self.ids["records"] = records

            evidence: dict[str, int] = {}
            for scope, record_key, uploader in (
                ("a", "a_edinburg", self.ids["faculty_a"]),
                ("b", "b_edinburg", self.ids["faculty_b"]),
            ):
                storage_key = (
                    f"{self.ids['organization']}/{self.ids['program']}/"
                    f"{scope}-scope-evidence.txt"
                )
                destination = self.upload_folder / storage_key
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(f"{scope.upper()}_EVIDENCE_BYTES".encode())
                evidence[f"{scope}_file"] = db.execute(
                    """INSERT INTO evidence_items
                       (organization_id,program_id,assessment_id,title,description,
                        evidence_type,storage_key,original_filename,mime_type,uploaded_by)
                       VALUES (?,?,?,?,?,'student_work',?,?,?,?)""",
                    (
                        self.ids["organization"],
                        self.ids["program"],
                        records[record_key],
                        f"{scope.upper()}_SCOPE_EVIDENCE_TITLE",
                        f"{scope.upper()}_SCOPE_EVIDENCE_DESCRIPTION",
                        storage_key,
                        f"{scope}-evidence.txt",
                        "text/plain",
                        uploader,
                    ),
                ).lastrowid
            programwide_storage_key = (
                f"{self.ids['organization']}/{self.ids['program']}/"
                "programwide-secret-evidence.txt"
            )
            programwide_destination = self.upload_folder / programwide_storage_key
            programwide_destination.parent.mkdir(parents=True, exist_ok=True)
            programwide_destination.write_bytes(b"PROGRAMWIDE_SECRET_BYTES")
            evidence["programwide"] = db.execute(
                """INSERT INTO evidence_items
                   (organization_id,program_id,assessment_id,title,description,
                    evidence_type,storage_key,original_filename,mime_type,uploaded_by)
                   VALUES (?,?,NULL,'PROGRAMWIDE_SECRET_EVIDENCE',
                           'Not linked to a faculty course','other',
                           ?,'programwide-secret.txt','text/plain',?)""",
                (
                    self.ids["organization"],
                    self.ids["program"],
                    programwide_storage_key,
                    self.ids["owner"],
                ),
            ).lastrowid
            self.ids["evidence"] = evidence

            actions: dict[str, int] = {}
            actions["a"] = db.execute(
                """INSERT INTO improvement_actions
                   (program_id,outcome_id,assessment_id,title,description,
                    owner_user_id,status,created_by)
                   VALUES (?,?,?,'A_SCOPE_IMPROVEMENT_ACTION',
                           'Linked only to faculty A course evidence',?,'planned',?)""",
                (
                    self.ids["program"],
                    outcome_id,
                    records["a_edinburg"],
                    self.ids["faculty_a"],
                    self.ids["faculty_a"],
                ),
            ).lastrowid
            actions["b"] = db.execute(
                """INSERT INTO improvement_actions
                   (program_id,outcome_id,assessment_id,title,description,
                    owner_user_id,status,created_by)
                   VALUES (?,?,?,'B_SECRET_IMPROVEMENT_ACTION',
                           'Linked only to faculty B course evidence',?,'planned',?)""",
                (
                    self.ids["program"],
                    outcome_id,
                    records["b_edinburg"],
                    self.ids["faculty_b"],
                    self.ids["faculty_b"],
                ),
            ).lastrowid
            actions["programwide"] = db.execute(
                """INSERT INTO improvement_actions
                   (program_id,outcome_id,assessment_id,title,description,status,created_by)
                   VALUES (?,?,NULL,'PROGRAMWIDE_SECRET_ACTION',
                           'Not linked to a faculty course','planned',?)""",
                (self.ids["program"], outcome_id, self.ids["owner"]),
            ).lastrowid
            self.ids["actions"] = actions
            db.commit()

    def _assert_contains_only_scope_a(self, response) -> None:
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"MECE 3315", response.data)
        self.assertNotIn(b"MECE 2340", response.data)
        self.assertNotIn(b"B_SECRET", response.data)
        self.assertNotIn(b"PROGRAMWIDE_SECRET", response.data)

    def test_faculty_read_surfaces_and_chart_inputs_are_course_scoped(self) -> None:
        self.as_user(self.ids["faculty_a"])
        records = self.ids["records"]

        dashboard = self.client.get("/")
        self._assert_contains_only_scope_a(dashboard)
        self.assertIn(b"A_SCOPE_IMPROVEMENT_ACTION", dashboard.data)

        assessment_list = self.client.get("/assessments")
        self._assert_contains_only_scope_a(assessment_list)
        self.assertIn(b"A_SCOPE_EDINBURG_TOOL", assessment_list.data)
        self.assertIn(b"A_SCOPE_BROWNSVILLE_TOOL", assessment_list.data)
        crafted_list = self.client.get(
            "/assessments", query_string={"course_id": self.course_b}
        )
        self.assertIn(crafted_list.status_code, {200, 403})
        self.assertNotIn(b"B_SECRET", crafted_list.data)

        for record_id in (records["a_edinburg"], records["a_brownsville"]):
            with self.subTest(authorized_record=record_id):
                detail = self.client.get(f"/assessments/{record_id}/edit")
                self.assertEqual(detail.status_code, 200)
        for record_id in (
            records["b_edinburg"],
            records["b_brownsville"],
            records["b_unassigned"],
        ):
            with self.subTest(forbidden_record=record_id):
                self.assertEqual(
                    self.client.get(f"/assessments/{record_id}/edit").status_code,
                    403,
                )

        real_generate_charts = routes.generate_charts
        with patch.object(
            routes, "generate_charts", wraps=real_generate_charts
        ) as chart_mock:
            analytics = self.client.get("/analytics")
        self._assert_contains_only_scope_a(analytics)
        chart_rows = list(chart_mock.call_args.args[0])
        self.assertEqual(
            {row["id"] for row in chart_rows},
            {records["a_edinburg"], records["a_brownsville"]},
        )
        self.assertEqual({row["course_id"] for row in chart_rows}, {self.course_a})
        self.assertEqual(
            self.client.get(
                "/analytics",
                query_string={"course_selection": "explicit", "course_id": self.course_b},
            ).status_code,
            403,
        )

        with patch.object(
            routes, "generate_charts", wraps=real_generate_charts
        ) as report_chart_mock:
            report = self.client.get("/report")
        self._assert_contains_only_scope_a(report)
        self.assertIn(b"A_SCOPE_EDINBURG_TOOL", report.data)
        self.assertIn(b"A_SCOPE_BROWNSVILLE_TOOL", report.data)
        self.assertIn(b"A_SCOPE_IMPROVEMENT_ACTION", report.data)
        self.assertIn(b"A_SCOPE_EVIDENCE_TITLE", report.data)
        report_rows = list(report_chart_mock.call_args.args[0])
        self.assertEqual(
            {row["id"] for row in report_rows},
            {records["a_edinburg"], records["a_brownsville"]},
        )
        self.assertIn(b"Campus assignment pending</dt><dd>0", report.data)

        actions = self.client.get("/actions")
        self.assertEqual(actions.status_code, 200)
        self.assertIn(b"A_SCOPE_IMPROVEMENT_ACTION", actions.data)
        self.assertNotIn(b"B_SECRET_IMPROVEMENT_ACTION", actions.data)
        self.assertNotIn(b"PROGRAMWIDE_SECRET_ACTION", actions.data)
        self.assertNotIn(b"Create action", actions.data)

    def test_faculty_csv_evidence_and_crafted_requests_cannot_cross_courses(self) -> None:
        self.as_user(self.ids["faculty_a"])
        records = self.ids["records"]
        evidence = self.ids["evidence"]
        actions = self.ids["actions"]

        exported = self.client.get("/export/assessments.csv")
        self.assertEqual(exported.status_code, 200)
        rows = list(csv.DictReader(io.StringIO(exported.text)))
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["course"] for row in rows}, {"MECE 3315"})
        self.assertEqual(
            {row["assessment_tool"] for row in rows},
            {"A_SCOPE_EDINBURG_TOOL", "A_SCOPE_BROWNSVILLE_TOOL"},
        )
        self.assertEqual(
            self.client.get(
                "/export/assessments.csv",
                query_string={"course_selection": "explicit", "course_id": self.course_b},
            ).status_code,
            403,
        )

        authorized_download = self.client.get(
            f"/evidence/{evidence['a_file']}/download"
        )
        self.assertEqual(authorized_download.status_code, 200)
        self.assertEqual(authorized_download.data, b"A_EVIDENCE_BYTES")
        self.assertEqual(
            self.client.get(f"/evidence/{evidence['b_file']}/download").status_code,
            403,
        )
        self.assertEqual(
            self.client.get(
                f"/evidence/{evidence['programwide']}/download"
            ).status_code,
            404,
        )

        # Every crafted write is rejected before it can disclose or mutate the
        # other faculty member's course data.
        self.assertEqual(
            self.client.post(
                f"/assessments/{records['b_edinburg']}/edit",
                data={"csrf_token": self.csrf()},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                f"/assessments/{records['b_edinburg']}/status",
                data={"csrf_token": self.csrf(), "action": "submit"},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                f"/assessments/{records['b_edinburg']}/evidence",
                data={"csrf_token": self.csrf(), "title": "forged"},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                f"/actions/{actions['b']}/update",
                data={
                    "csrf_token": self.csrf(),
                    "status": "completed",
                    "impact_summary": "forged",
                },
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                "/actions",
                data={
                    "csrf_token": self.csrf(),
                    "title": "FORGED_PROGRAMWIDE_ACTION",
                    "description": "Faculty cannot create unscoped program data.",
                },
            ).status_code,
            403,
        )

        forged_new = {
            "csrf_token": self.csrf(),
            "term_id": self.dimensions["term"],
            "course_id": self.course_b,
            "outcome_id": self.dimensions["outcome"],
            "indicator_id": self.dimensions["indicator"],
            "rubric_id": self.dimensions["rubric"],
        }
        self.assertEqual(
            self.client.post("/assessments/new", data=forged_new).status_code,
            403,
        )
        with self.app.app_context():
            db = get_db()
            self.assertFalse(
                db.execute(
                    "SELECT 1 FROM improvement_actions WHERE title='FORGED_PROGRAMWIDE_ACTION'"
                ).fetchone()
            )
            self.assertEqual(
                db.execute(
                    "SELECT status FROM improvement_actions WHERE id=?",
                    (actions["b"],),
                ).fetchone()[0],
                "planned",
            )

    def test_second_faculty_receives_the_inverse_course_scope(self) -> None:
        self.as_user(self.ids["faculty_b"])
        records = self.ids["records"]

        assessment_list = self.client.get("/assessments")
        self.assertEqual(assessment_list.status_code, 200)
        self.assertIn(b"MECE 2340", assessment_list.data)
        self.assertIn(b"B_SECRET_EDINBURG_TOOL", assessment_list.data)
        self.assertIn(b"B_SECRET_BROWNSVILLE_TOOL", assessment_list.data)
        self.assertNotIn(b"MECE 3315", assessment_list.data)
        self.assertNotIn(b"A_SCOPE", assessment_list.data)

        analytics = self.client.get("/analytics")
        self.assertEqual(analytics.status_code, 200)
        self.assertIn(b"MECE 2340", analytics.data)
        self.assertNotIn(b"MECE 3315", analytics.data)

        report = self.client.get("/report")
        self.assertEqual(report.status_code, 200)
        self.assertIn(b"B_SECRET_EDINBURG_TOOL", report.data)
        self.assertIn(b"B_SECRET_BROWNSVILLE_TOOL", report.data)
        self.assertNotIn(b"A_SCOPE_EDINBURG_TOOL", report.data)
        self.assertIn(b"B_SECRET_IMPROVEMENT_ACTION", report.data)
        self.assertNotIn(b"A_SCOPE_IMPROVEMENT_ACTION", report.data)
        self.assertIn(b"B_SCOPE_EVIDENCE_TITLE", report.data)
        self.assertNotIn(b"A_SCOPE_EVIDENCE_TITLE", report.data)

        self.assertEqual(
            self.client.get(
                f"/assessments/{records['a_edinburg']}/edit"
            ).status_code,
            403,
        )

    def test_faculty_cannot_open_administration_or_bulk_data_endpoints(self) -> None:
        self.as_user(self.ids["faculty_a"])
        for path in (
            "/configuration",
            "/users",
            "/audit",
            "/utrgv/faculty",
            "/utrgv/legacy",
            "/import/template.csv",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 403)
        self.assertEqual(
            self.client.post(
                "/assessments/bulk-approve",
                data={
                    "csrf_token": self.csrf(),
                    "selection_mode": "all",
                },
            ).status_code,
            403,
        )

    def test_owner_retains_complete_visibility_and_direct_access(self) -> None:
        self.as_user(self.ids["owner"])
        records = self.ids["records"]
        evidence = self.ids["evidence"]

        dashboard = self.client.get("/")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn(b"MECE 3315", dashboard.data)
        self.assertIn(b"MECE 2340", dashboard.data)
        self.assertIn(b"A_SCOPE_IMPROVEMENT_ACTION", dashboard.data)
        self.assertIn(b"B_SECRET_IMPROVEMENT_ACTION", dashboard.data)
        self.assertIn(b"PROGRAMWIDE_SECRET_ACTION", dashboard.data)

        assessment_list = self.client.get("/assessments")
        for token in (
            b"A_SCOPE_EDINBURG_TOOL",
            b"A_SCOPE_BROWNSVILLE_TOOL",
            b"B_SECRET_EDINBURG_TOOL",
            b"B_SECRET_BROWNSVILLE_TOOL",
            b"B_SECRET_UNASSIGNED_TOOL",
        ):
            self.assertIn(token, assessment_list.data)

        real_generate_charts = routes.generate_charts
        with patch.object(
            routes, "generate_charts", wraps=real_generate_charts
        ) as chart_mock:
            analytics = self.client.get("/analytics")
        self.assertEqual(analytics.status_code, 200)
        chart_rows = list(chart_mock.call_args.args[0])
        self.assertEqual(
            {row["id"] for row in chart_rows},
            {
                records["a_edinburg"],
                records["a_brownsville"],
                records["b_edinburg"],
                records["b_brownsville"],
            },
        )
        self.assertEqual(
            {row["course_id"] for row in chart_rows}, {self.course_a, self.course_b}
        )

        report = self.client.get("/report")
        for token in (
            b"A_SCOPE_EDINBURG_TOOL",
            b"B_SECRET_EDINBURG_TOOL",
            b"A_SCOPE_IMPROVEMENT_ACTION",
            b"B_SECRET_IMPROVEMENT_ACTION",
            b"PROGRAMWIDE_SECRET_ACTION",
            b"A_SCOPE_EVIDENCE_TITLE",
            b"B_SCOPE_EVIDENCE_TITLE",
            b"PROGRAMWIDE_SECRET_EVIDENCE",
        ):
            self.assertIn(token, report.data)
        self.assertIn(b"Campus assignment pending</dt><dd>1", report.data)

        exported = self.client.get("/export/assessments.csv")
        rows = list(csv.DictReader(io.StringIO(exported.text)))
        self.assertEqual(len(rows), 5)
        self.assertEqual({row["course"] for row in rows}, {"MECE 3315", "MECE 2340"})

        for record_id in records.values():
            with self.subTest(record_id=record_id):
                self.assertEqual(
                    self.client.get(f"/assessments/{record_id}/edit").status_code,
                    200,
                )
        for key in ("a_file", "b_file"):
            with self.subTest(evidence=key):
                self.assertEqual(
                    self.client.get(
                        f"/evidence/{evidence[key]}/download"
                    ).status_code,
                    200,
                )


if __name__ == "__main__":
    unittest.main()
