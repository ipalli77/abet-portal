from __future__ import annotations

import csv
import io
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from flask import template_rendered
from werkzeug.security import generate_password_hash

from abet_platform import create_app
from abet_platform.analysis_engine import analyze_rows
from abet_platform.db import get_db


@contextmanager
def captured_templates(app):
    """Capture rendered template contexts without coupling tests to page markup."""
    rendered = []

    def record(_sender, template, context, **_extra):
        rendered.append((template, context))

    template_rendered.connect(record, app)
    try:
        yield rendered
    finally:
        template_rendered.disconnect(record, app)


class AnalyticsFilterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "analytics-test-secret",
                "DATABASE": str(root / "analytics.db"),
                "UPLOAD_FOLDER": str(root / "uploads"),
            }
        )
        self.client = self.app.test_client()
        self._bootstrap_owner()
        self.ids = self._seed_records()

    def tearDown(self):
        self.temp.cleanup()

    def csrf(self):
        with self.client.session_transaction() as session:
            return session["csrf_token"]

    def _bootstrap_owner(self):
        self.client.get("/setup")
        response = self.client.post(
            "/setup",
            data={
                "csrf_token": self.csrf(),
                "institution": "Analytics University",
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
            data={
                "csrf_token": self.csrf(),
                "email": "owner@example.edu",
                "password": "long-secure-password",
            },
        )
        self.assertEqual(response.status_code, 302)

    @staticmethod
    def _insert_record(db, dimensions, course_id, *, status, attainment, bloom="Analyze"):
        record_id = db.execute(
            """INSERT INTO assessment_records
               (program_id,term_id,course_id,outcome_id,indicator_id,rubric_id,collected_by,
                method,assessment_tool,bloom_level,sample_size,target,status)
               VALUES (?,?,?,?,?,?,?,'direct',?,?,100,70,?)""",
            (
                dimensions["program_id"],
                dimensions["term_id"],
                course_id,
                dimensions["outcome_id"],
                dimensions["indicator_id"],
                dimensions["rubric_id"],
                dimensions["owner_id"],
                f"Unique tool for record {course_id}-{status}",
                bloom,
                status,
            ),
        ).lastrowid
        counts = (attainment, 0, 100 - attainment, 0)
        db.executemany(
            "INSERT INTO assessment_results(assessment_id,rubric_level_id,student_count) VALUES (?,?,?)",
            [
                (record_id, level_id, count)
                for level_id, count in zip(dimensions["level_ids"], counts)
            ],
        )
        return record_id

    def _seed_records(self):
        with self.app.app_context():
            db = get_db()
            program_id = db.execute("SELECT id FROM programs WHERE code='BSME'").fetchone()[0]
            organization_id = db.execute("SELECT organization_id FROM programs WHERE id=?", (program_id,)).fetchone()[0]
            owner_id = db.execute("SELECT id FROM users WHERE email='owner@example.edu'").fetchone()[0]
            term_id = db.execute("SELECT id FROM academic_terms WHERE program_id=?", (program_id,)).fetchone()[0]
            outcome_id = db.execute(
                "SELECT id FROM outcomes WHERE program_id=? ORDER BY display_order", (program_id,)
            ).fetchone()[0]
            indicator_id = db.execute(
                "SELECT id FROM performance_indicators WHERE outcome_id=? ORDER BY display_order", (outcome_id,)
            ).fetchone()[0]
            rubric_id = db.execute("SELECT id FROM rubrics WHERE program_id=?", (program_id,)).fetchone()[0]
            level_ids = [
                row[0]
                for row in db.execute(
                    "SELECT id FROM rubric_levels WHERE rubric_id=? ORDER BY display_order", (rubric_id,)
                )
            ]
            dimensions = {
                "program_id": program_id,
                "owner_id": owner_id,
                "term_id": term_id,
                "outcome_id": outcome_id,
                "indicator_id": indicator_id,
                "rubric_id": rubric_id,
                "level_ids": level_ids,
            }
            course_ids = {}
            for code in ("ME 101", "ME 202", "ME 303"):
                course_ids[code] = db.execute(
                    "INSERT INTO courses(program_id,code,name) VALUES (?,?,?)",
                    (program_id, code, f"Course {code}"),
                ).lastrowid
            record_ids = {
                "approved_a": self._insert_record(
                    db, dimensions, course_ids["ME 101"], status="approved", attainment=81
                ),
                "draft_a": self._insert_record(
                    db, dimensions, course_ids["ME 101"], status="draft", attainment=42, bloom="Apply"
                ),
                "submitted_b": self._insert_record(
                    db, dimensions, course_ids["ME 202"], status="submitted", attainment=63
                ),
                "approved_c": self._insert_record(
                    db, dimensions, course_ids["ME 303"], status="approved", attainment=92, bloom="Create"
                ),
            }
            other_program_id = db.execute(
                "INSERT INTO programs(organization_id,code,name) VALUES (?,?,?)",
                (organization_id, "OTHER", "Other Engineering"),
            ).lastrowid
            other_course_id = db.execute(
                "INSERT INTO courses(program_id,code,name) VALUES (?,?,?)",
                (other_program_id, "XX 999", "Other program course"),
            ).lastrowid
            db.commit()
            return {
                "organization": organization_id,
                "program": program_id,
                "owner": owner_id,
                "courses": course_ids,
                "records": record_ids,
                "other_course": other_course_id,
            }

    def _analytics_context(self, query_string=None):
        with captured_templates(self.app) as rendered:
            response = self.client.get("/analytics", query_string=query_string)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(rendered)
        self.assertEqual(rendered[-1][0].name, "analytics.html")
        return rendered[-1][1]

    def test_repeated_course_filter_selects_exact_union_without_duplicates(self):
        course_a = self.ids["courses"]["ME 101"]
        course_c = self.ids["courses"]["ME 303"]
        context = self._analytics_context(
            [
                ("course_id", str(course_a)),
                ("course_id", str(course_c)),
                ("course_id", str(course_a)),
                ("evidence_scope", "all"),
            ]
        )

        self.assertEqual(context["selected_course_ids"], {course_a, course_c})
        self.assertEqual(
            {row["id"] for row in context["records"]},
            {
                self.ids["records"]["approved_a"],
                self.ids["records"]["draft_a"],
                self.ids["records"]["approved_c"],
            },
        )
        self.assertEqual(len(context["records"]), 3)

    def test_official_scope_is_default_and_preview_scope_is_explicit(self):
        official = self._analytics_context()
        self.assertEqual(official["evidence_scope"], "approved")
        self.assertEqual(
            {row["status"] for row in official["records"]},
            {"approved"},
        )
        self.assertEqual(
            {row["id"] for row in official["records"]},
            {
                self.ids["records"]["approved_a"],
                self.ids["records"]["approved_c"],
            },
        )
        self.assertEqual(official["scope_metrics"]["count"], 2)
        self.assertEqual(official["scope_metrics"]["average"], 86.5)
        self.assertEqual(official["scope_metrics"]["met_count"], 2)

        preview = self._analytics_context({"evidence_scope": "all"})
        self.assertEqual(preview["evidence_scope"], "all")
        self.assertEqual(
            {row["status"] for row in preview["records"]},
            {"approved", "draft", "submitted"},
        )
        # Workflow summaries must not relabel preview evidence as approved.
        self.assertEqual(preview["metrics"]["approved"], 2)
        self.assertEqual(preview["metrics"]["draft"], 1)
        self.assertEqual(preview["metrics"]["submitted"], 1)
        self.assertEqual(preview["scope_metrics"]["count"], 4)
        self.assertEqual(preview["scope_metrics"]["average"], 69.5)
        self.assertEqual(preview["scope_metrics"]["met_count"], 2)

        self.assertEqual(official["analysis"]["row_count"], 2)
        self.assertEqual(preview["analysis"]["row_count"], 4)
        for statistic in ("kruskal_wallis", "cliffs_delta", "trend"):
            self.assertIn(statistic, preview["analysis"])
            self.assertIn("status", preview["analysis"][statistic])
        self.assertEqual(
            set(preview["charts"]),
            {"trend_line"},  # Other charts are rendered only on their own tabs.
        )

    def test_engine_course_and_status_arguments_narrow_rows_without_weighting(self):
        course_a = self.ids["courses"]["ME 101"]
        preview = self._analytics_context({"evidence_scope": "all"})
        rows = preview["records"]

        selected = analyze_rows(rows, selected_courses=[course_a])
        self.assertEqual(selected["row_count"], 2)
        self.assertEqual(selected["selected_courses"], [course_a])
        self.assertAlmostEqual(selected["courses"][0]["mean"], 61.5, places=10)

        approved = analyze_rows(rows, approved_only=True)
        self.assertEqual(approved["row_count"], 2)
        self.assertEqual({row["status"] for row in approved["rows"]}, {"approved"})

        drafts = analyze_rows(rows, statuses=["draft"])
        self.assertEqual(drafts["row_count"], 1)
        self.assertEqual(drafts["rows"][0]["id"], self.ids["records"]["draft_a"])

    def test_filtered_export_uses_the_same_courses_and_evidence_scope(self):
        course_a = self.ids["courses"]["ME 101"]
        course_c = self.ids["courses"]["ME 303"]
        response = self.client.get(
            "/export/assessments.csv",
            query_string=[
                ("course_id", str(course_a)),
                ("course_id", str(course_c)),
                ("evidence_scope", "approved"),
            ],
        )
        self.assertEqual(response.status_code, 200)
        rows = list(csv.DictReader(io.StringIO(response.text)))
        self.assertEqual({row["course"] for row in rows}, {"ME 101", "ME 303"})
        self.assertEqual({row["status"] for row in rows}, {"approved"})
        self.assertEqual(len(rows), 2)

    def test_invalid_and_cross_program_course_filters_are_rejected(self):
        self.assertEqual(self.client.get("/analytics?course_id=not-a-number").status_code, 400)
        self.assertEqual(
            self.client.get("/analytics?course_selection=explicit").status_code,
            400,
        )
        self.assertEqual(
            self.client.get(
                "/analytics", query_string={"course_id": self.ids["other_course"]}
            ).status_code,
            403,
        )
        self.assertEqual(self.client.get("/analytics?evidence_scope=unknown").status_code, 400)

    def test_faculty_can_only_filter_and_analyze_assigned_courses(self):
        assigned_course = self.ids["courses"]["ME 101"]
        unassigned_course = self.ids["courses"]["ME 303"]
        with self.app.app_context():
            db = get_db()
            faculty_id = db.execute(
                "INSERT INTO users(email,full_name,password_hash) VALUES (?,?,?)",
                ("faculty@example.edu", "Faculty Member", generate_password_hash("faculty-password-long")),
            ).lastrowid
            db.execute(
                "INSERT INTO memberships(user_id,organization_id,role) VALUES (?,?,'faculty')",
                (faculty_id, self.ids["organization"]),
            )
            db.execute(
                "INSERT INTO program_members(program_id,user_id,access_level) VALUES (?,?,'editor')",
                (self.ids["program"], faculty_id),
            )
            db.execute(
                "INSERT INTO course_assignments(course_id,user_id) VALUES (?,?)",
                (assigned_course, faculty_id),
            )
            db.commit()

        with self.client.session_transaction() as session:
            session.clear()
            session["user_id"] = faculty_id
            session["organization_id"] = self.ids["organization"]
            session["program_id"] = self.ids["program"]

        context = self._analytics_context({"evidence_scope": "all"})
        self.assertEqual(context["selected_course_ids"], {assigned_course})
        self.assertEqual({row["course_id"] for row in context["records"]}, {assigned_course})
        self.assertEqual({course["id"] for course in context["courses"]}, {assigned_course})
        self.assertEqual(
            self.client.get(
                "/analytics", query_string={"course_id": unassigned_course, "evidence_scope": "all"}
            ).status_code,
            403,
        )


class BundledLegacyAnalyticsParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.legacy_source = (
            Path(__file__).resolve().parents[1] / "edinburg_abet_data.db"
        )
        if not cls.legacy_source.is_file():
            raise unittest.SkipTest(
                "The optional bundled edinburg_abet_data.db is not available."
            )

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "legacy-analytics-test-secret",
                "DATABASE": str(root / "utrgv-analytics.db"),
                "UPLOAD_FOLDER": str(root / "uploads"),
                "EDITION": "utrgv_mece",
                "PRODUCT_NAME": "UTRGV ME Accreditation Hub",
                "CUSTOMER_NAME": "UTRGV Department of Mechanical Engineering",
                "LEGACY_DATABASE": str(self.legacy_source),
            }
        )
        self.client = self.app.test_client()
        self.client.get("/setup")
        with self.client.session_transaction() as session:
            csrf = session["csrf_token"]
        response = self.client.post(
            "/setup",
            data={
                "csrf_token": csrf,
                "full_name": "Accreditation Director",
                "email": "isaac.palli@utrgv.edu",
                "password": "owner-password-long",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.client.get("/login")
        with self.client.session_transaction() as session:
            csrf = session["csrf_token"]
        response = self.client.post(
            "/login",
            data={
                "csrf_token": csrf,
                "email": "isaac.palli@utrgv.edu",
                "password": "owner-password-long",
            },
        )
        self.assertEqual(response.status_code, 302)

        from abet_platform.legacy_import import import_legacy_records

        with self.app.app_context():
            db = get_db()
            program_id = db.execute("SELECT id FROM programs WHERE code='BSME'").fetchone()[0]
            owner_id = db.execute("SELECT id FROM users WHERE email='isaac.palli@utrgv.edu'").fetchone()[0]
            with db:
                result = import_legacy_records(
                    db,
                    self.legacy_source,
                    program_id=program_id,
                    imported_by=owner_id,
                    campus="Edinburg",
                    source_key="edinburg-parity",
                )
            self.assertEqual(result["imported"], 318)
            self.course_ids = {
                row["code"]: row["id"]
                for row in db.execute(
                    "SELECT id,code FROM courses WHERE program_id=? AND code IN ('MECE 3315','MECE 3320')",
                    (program_id,),
                )
            }

    def tearDown(self):
        self.temp.cleanup()

    def _context(self, *, evidence_scope):
        query = [
            ("course_id", str(self.course_ids["MECE 3315"])),
            ("course_id", str(self.course_ids["MECE 3320"])),
            ("evidence_scope", evidence_scope),
        ]
        with captured_templates(self.app) as rendered:
            response = self.client.get("/analytics", query_string=query)
        self.assertEqual(response.status_code, 200)
        return rendered[-1][1]

    def test_preview_matches_exact_legacy_percentages_for_selected_courses(self):
        with sqlite3.connect(self.legacy_source) as legacy:
            expected = {
                row[0]: float(row[1])
                for row in legacy.execute(
                    """SELECT id, expert + practitioner
                       FROM abet_entries
                       WHERE course IN ('MECE 3315','MECE 3320')"""
                )
            }
        self.assertEqual(len(expected), 26)

        context = self._context(evidence_scope="all")
        actual = {
            row["legacy_source_record_id"]: float(row["attainment"])
            for row in context["records"]
        }
        self.assertEqual(actual.keys(), expected.keys())
        for source_id, expected_attainment in expected.items():
            self.assertAlmostEqual(actual[source_id], expected_attainment, places=10)

        self.assertEqual(context["scope_metrics"]["count"], 26)
        self.assertAlmostEqual(context["scope_metrics"]["average"], 70.8, places=10)
        self.assertEqual(context["scope_metrics"]["met_count"], 16)

        analysis = context["analysis"]
        self.assertEqual(analysis["row_count"], 26)
        self.assertEqual(
            analysis["selected_courses"],
            sorted(self.course_ids.values()),
        )
        course_means = {
            item["label"].split(" — ", 1)[0]: item["mean"]
            for item in analysis["courses"]
        }
        self.assertAlmostEqual(course_means["MECE 3315"], 69.6, places=10)
        self.assertAlmostEqual(
            course_means["MECE 3320"],
            71.04761904761905,
            places=10,
        )

        expected_terms = [
            ("Spring 2022", 3, 68.0),
            ("Spring 2023", 7, 69.42857142857143),
            ("Fall 2023", 1, 75.0),
            ("Spring 2024", 7, 64.85714285714286),
            ("Fall 2024", 1, 78.0),
            ("Spring 2025", 7, 77.57142857142857),
        ]
        self.assertEqual(
            [item["label"] for item in analysis["terms"]],
            [label for label, _count, _mean in expected_terms],
        )
        for item, (_label, count, mean) in zip(analysis["terms"], expected_terms):
            self.assertEqual(item["count"], count)
            self.assertAlmostEqual(item["mean"], mean, places=10)

        self.assertEqual(analysis["kruskal_wallis"]["status"], "available")
        self.assertEqual(analysis["cliffs_delta"]["status"], "available")
        self.assertEqual(analysis["trend"]["status"], "available")
        self.assertEqual(analysis["trend"]["term_count"], 6)
        charts = context["charts"]
        self.assertEqual(
            set(charts),
            {"trend_line"},
        )
        for chart in charts.values():
            self.assertIn("available", chart)
            self.assertTrue(chart["title"])
            self.assertTrue(chart["alt_text"])
            if chart["available"]:
                self.assertTrue(chart["data_uri"].startswith("data:image/png;base64,"))
            else:
                self.assertTrue(chart["reason"])

        by_course = {item["label"].split(" — ", 1)[0]: item for item in context["by_course"]}
        # Preview records remain migration drafts, so official-only aggregate fields
        # must not silently represent them as approved evidence.
        self.assertIsNone(by_course["MECE 3315"]["average"])
        self.assertIsNone(by_course["MECE 3320"]["average"])

    def test_official_scope_does_not_promote_imported_drafts(self):
        context = self._context(evidence_scope="approved")
        self.assertEqual(context["records"], [])
        self.assertEqual(context["metrics"]["approved"], 0)


if __name__ == "__main__":
    unittest.main()
