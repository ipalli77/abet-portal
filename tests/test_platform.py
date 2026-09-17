from __future__ import annotations

import csv
import io
import tempfile
import unittest
from pathlib import Path

from abet_platform import create_app
from abet_platform.analytics import attainment_percent, summarize_records
from abet_platform.db import get_db


class PlatformFlowTests(unittest.TestCase):
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

    def tearDown(self):
        self.temp.cleanup()

    def csrf(self):
        with self.client.session_transaction() as session:
            return session["csrf_token"]

    def bootstrap_and_login(self):
        self.client.get("/setup")
        response = self.client.post(
            "/setup",
            data={
                "csrf_token": self.csrf(),
                "institution": "Example University",
                "program_name": "Mechanical Engineering",
                "program_code": "BSME",
                "full_name": "Program Owner",
                "email": "owner@example.edu",
                "password": "long-secure-password",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.client.get("/login")
        response = self.client.post(
            "/login",
            data={"csrf_token": self.csrf(), "email": "owner@example.edu", "password": "long-secure-password"},
        )
        self.assertEqual(response.status_code, 302)

    def add_course(self):
        response = self.client.post(
            "/configuration",
            data={
                "csrf_token": self.csrf(),
                "kind": "course",
                "code": "ME 301",
                "name": "Engineering Analysis",
                "description": "Core analysis course",
            },
        )
        self.assertEqual(response.status_code, 302)

    def dimensions(self):
        with self.app.app_context():
            db = get_db()
            return {
                "program": db.execute("SELECT * FROM programs").fetchone(),
                "term": db.execute("SELECT * FROM academic_terms").fetchone(),
                "course": db.execute("SELECT * FROM courses").fetchone(),
                "outcome": db.execute("SELECT * FROM outcomes ORDER BY display_order").fetchone(),
                "indicator": db.execute("SELECT * FROM performance_indicators ORDER BY id").fetchone(),
                "rubric": db.execute("SELECT * FROM rubrics").fetchone(),
                "levels": db.execute("SELECT * FROM rubric_levels ORDER BY display_order").fetchall(),
            }

    def test_first_run_setup_seeds_editable_model(self):
        self.bootstrap_and_login()
        with self.app.app_context():
            db = get_db()
            self.assertEqual(db.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0], 7)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM rubric_levels").fetchone()[0], 4)
            self.assertEqual(db.execute("SELECT role FROM memberships").fetchone()[0], "owner")
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_complete_assessment_review_and_export_flow(self):
        self.bootstrap_and_login()
        self.add_course()
        dims = self.dimensions()
        payload = {
            "csrf_token": self.csrf(),
            "term_id": dims["term"]["id"],
            "course_id": dims["course"]["id"],
            "outcome_id": dims["outcome"]["id"],
            "indicator_id": dims["indicator"]["id"],
            "rubric_id": dims["rubric"]["id"],
            "method": "direct",
            "assessment_tool": "Design problem rubric",
            "bloom_level": "Analyze",
            "sample_size": "10",
            "target": "70",
            "rationale": "Aligned direct evidence",
            "observations": "Students modeled constraints well.",
            "action_notes": "Add an earlier constraint-identification exercise.",
        }
        counts = [3, 5, 1, 1]
        for level, count in zip(dims["levels"], counts):
            payload[f"level_{level['id']}"] = str(count)
        response = self.client.post("/assessments/new", data=payload)
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            record_id = get_db().execute("SELECT id FROM assessment_records").fetchone()[0]
        response = self.client.post(
            f"/assessments/{record_id}/status", data={"csrf_token": self.csrf(), "action": "submit"}
        )
        self.assertEqual(response.status_code, 302)
        response = self.client.post(
            f"/assessments/{record_id}/status", data={"csrf_token": self.csrf(), "action": "approve"}
        )
        self.assertEqual(response.status_code, 302)
        analytics = self.client.get("/analytics")
        self.assertIn(b"80.0%", analytics.data)
        exported = self.client.get("/export/assessments.csv")
        rows = list(csv.DictReader(io.StringIO(exported.text)))
        self.assertEqual(rows[0]["status"], "approved")
        self.assertEqual(rows[0]["attainment"], "80.0")
        for path in (
            "/",
            "/configuration",
            "/assessments",
            f"/assessments/{record_id}/edit",
            "/actions",
            "/analytics",
            "/report",
            "/users",
            "/audit",
            "/account/password",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(b"AccreditationOS", response.data)

    def test_csrf_and_tenant_scoping_are_enforced(self):
        self.bootstrap_and_login()
        self.assertEqual(self.client.post("/configuration", data={"kind": "course"}).status_code, 400)
        with self.client.session_transaction() as session:
            session["program_id"] = 99999
        self.assertEqual(self.client.get("/").status_code, 404)


class AnalyticsTests(unittest.TestCase):
    def test_attainment_and_workflow_summary(self):
        levels = [
            {"student_count": 7, "is_attained": 1},
            {"student_count": 3, "is_attained": 0},
        ]
        self.assertEqual(attainment_percent(levels), 70.0)
        rows = [
            {"status": "approved", "attainment": 80, "target": 70},
            {"status": "approved", "attainment": 60, "target": 70},
            {"status": "submitted", "attainment": 90, "target": 70},
        ]
        summary = summarize_records(rows)
        self.assertEqual(summary["approved"], 2)
        self.assertEqual(summary["met_rate"], 50.0)
        self.assertEqual(summary["average"], 70.0)


if __name__ == "__main__":
    unittest.main()
