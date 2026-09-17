from __future__ import annotations

import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from matplotlib import pyplot
from matplotlib.collections import PolyCollection

from abet_platform import create_app
from abet_platform import analysis_engine
from abet_platform.analysis_engine import analyze_rows, generate_charts
from abet_platform.db import get_db


def assessment_row(
    *,
    indicator_id: int,
    indicator_code: str,
    term_id: int,
    term_label: str,
    term_order: int,
    attainment: float,
    target: float = 70,
    bloom_level: str = "Analyze",
    outcome_id: int = 1,
    outcome_code: str = "SLO1",
) -> dict[str, object]:
    """Build a realistic row for the public analysis/chart interface."""
    return {
        "course_id": 101,
        "course_code": "MECE 3320",
        "course_label": "MECE 3320 — Measurements and Instrumentation",
        "term_id": term_id,
        "term_label": term_label,
        "term_order": term_order,
        "outcome_id": outcome_id,
        "outcome_code": outcome_code,
        "outcome_label": f"{outcome_code}: Test outcome",
        "outcome_order": outcome_id,
        "indicator_id": indicator_id,
        "indicator_code": indicator_code,
        "indicator_label": f"{indicator_code}: Test indicator",
        "bloom_level": bloom_level,
        "attainment": attainment,
        "target": target,
        "status": "approved",
    }


def recursive_keys(value) -> list[str]:
    keys: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            keys.append(str(key))
            keys.extend(recursive_keys(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            keys.extend(recursive_keys(child))
    return keys


class FacetedIndicatorTrendChartTests(unittest.TestCase):
    """Acceptance tests for the PI-wise trend view requested by UTRGV.

    The metadata assertions are part of the accessibility contract. They also
    let the HTML presentation explain the same finding as the bitmap without
    attempting brittle pixel-by-pixel snapshot comparisons.
    """

    def assert_faceted_chart(
        self,
        rows: list[dict[str, object]],
        *,
        panel_count: int,
    ) -> tuple[dict[str, object], dict[str, object]]:
        chart = generate_charts(rows)["semester_indicator"]
        self.assertTrue(chart["available"], chart.get("reason"))
        self.assertEqual(chart.get("chart_type"), "faceted_pi_trend")
        self.assertIsNone(chart["reason"])
        self.assertTrue(str(chart["data_uri"]).startswith("data:image/png;base64,"))
        png = base64.b64decode(str(chart["png_base64"]))
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertGreater(len(png), 1_000)

        metadata = chart.get("metadata")
        self.assertIsInstance(metadata, dict)
        self.assertEqual(metadata.get("facet_by"), "performance_indicator")
        self.assertEqual(metadata.get("panel_count"), panel_count)
        self.assertEqual(len(metadata.get("panels", [])), panel_count)
        self.assertEqual(metadata.get("legend_title"), "Bloom level")
        self.assertIn("observed", str(chart["alt_text"]).casefold())
        self.assertIn("trend", str(chart["alt_text"]).casefold())
        return chart, metadata

    def test_single_pi_is_one_facet_with_chronological_terms_and_bloom_legend(self):
        rows = [
            assessment_row(
                indicator_id=1,
                indicator_code="PI-1",
                term_id=30,
                term_label="Fall 2024",
                term_order=30,
                attainment=78,
                bloom_level="Analyze",
            ),
            assessment_row(
                indicator_id=1,
                indicator_code="PI-1",
                term_id=10,
                term_label="Fall 2023",
                term_order=10,
                attainment=68,
                bloom_level="Understand",
            ),
            assessment_row(
                indicator_id=1,
                indicator_code="PI-1",
                term_id=20,
                term_label="Spring 2024",
                term_order=20,
                attainment=74,
                bloom_level="Apply",
            ),
        ]

        _chart, metadata = self.assert_faceted_chart(rows, panel_count=1)
        self.assertEqual(
            metadata["term_labels"],
            ["Fall 2023", "Spring 2024", "Fall 2024"],
        )
        self.assertEqual(
            metadata["bloom_levels"],
            ["Understand", "Apply", "Analyze"],
        )
        self.assertEqual(set(metadata["bloom_styles"]), set(metadata["bloom_levels"]))
        self.assertTrue(
            all(style.get("color") for style in metadata["bloom_styles"].values())
        )
        panel = metadata["panels"][0]
        self.assertEqual(panel["outcome_code"], "SLO1")
        self.assertEqual(panel["indicator_code"], "PI-1")
        self.assertEqual(panel["point_count"], 3)
        self.assertEqual(panel["term_labels"], metadata["term_labels"])
        self.assertEqual(panel["trend"]["status"], "available")

    def test_few_pis_render_as_separate_ordered_facets_not_overlaid_series(self):
        rows = []
        for indicator_id in (3, 1, 2):
            for term_id, term_label, attainment in (
                (2, "Spring 2024", 70 + indicator_id),
                (1, "Fall 2023", 66 + indicator_id),
                (3, "Fall 2024", 74 + indicator_id),
            ):
                rows.append(
                    assessment_row(
                        indicator_id=indicator_id,
                        indicator_code=f"PI-{indicator_id}",
                        term_id=term_id,
                        term_label=term_label,
                        term_order=term_id,
                        attainment=attainment,
                        bloom_level=("Understand", "Apply", "Analyze")[term_id - 1],
                    )
                )

        _chart, metadata = self.assert_faceted_chart(rows, panel_count=3)
        self.assertEqual(
            [panel["indicator_code"] for panel in metadata["panels"]],
            ["PI-1", "PI-2", "PI-3"],
        )
        self.assertTrue(all(panel["point_count"] == 3 for panel in metadata["panels"]))

        captured: dict[str, object] = {}

        def capture_chart(figure, **kwargs):
            captured["figure"] = figure
            captured.update(kwargs)
            return kwargs

        with patch.object(analysis_engine, "_chart", side_effect=capture_chart):
            analysis_engine._indicator_chart(analyze_rows(rows), pyplot)
        figure = captured["figure"]
        try:
            self.assertEqual(
                len(figure.axes),
                3,
                "Each performance indicator should have its own visual panel.",
            )
            self.assertTrue(
                all(axis.collections for axis in figure.axes),
                "Every PI panel should contain observed-point markers.",
            )
        finally:
            pyplot.close(figure)

    def test_many_pis_remain_available_instead_of_reinstating_the_old_series_limit(self):
        rows = []
        for indicator_id in range(1, 14):
            for term_id, attainment in ((1, 65 + indicator_id), (2, 67 + indicator_id)):
                rows.append(
                    assessment_row(
                        indicator_id=indicator_id,
                        indicator_code=f"PI-{indicator_id}",
                        term_id=term_id,
                        term_label=("Fall 2023", "Spring 2024")[term_id - 1],
                        term_order=term_id,
                        attainment=attainment,
                        bloom_level=("Apply", "Analyze")[term_id - 1],
                    )
                )

        chart, metadata = self.assert_faceted_chart(rows, panel_count=13)
        self.assertNotIn("no more than 12", str(chart["alt_text"]).casefold())
        self.assertEqual(
            [panel["indicator_code"] for panel in metadata["panels"]],
            [f"PI-{index}" for index in range(1, 14)],
        )

    def test_sparse_pi_stays_visible_but_does_not_receive_an_invented_trend(self):
        rows = [
            assessment_row(
                indicator_id=1,
                indicator_code="PI-1",
                term_id=term_id,
                term_label=term_label,
                term_order=term_id,
                attainment=attainment,
            )
            for term_id, term_label, attainment in (
                (1, "Fall 2023", 66),
                (2, "Spring 2024", 72),
                (3, "Fall 2024", 77),
            )
        ]
        rows.append(
            assessment_row(
                indicator_id=2,
                indicator_code="PI-2",
                term_id=2,
                term_label="Spring 2024",
                term_order=2,
                attainment=81,
                bloom_level="Evaluate",
            )
        )

        _chart, metadata = self.assert_faceted_chart(rows, panel_count=2)
        sparse = next(
            panel for panel in metadata["panels"] if panel["indicator_code"] == "PI-2"
        )
        self.assertEqual(sparse["point_count"], 1)
        self.assertEqual(sparse["trend"]["status"], "unavailable")
        self.assertIsNone(sparse["trend"].get("slope"))
        self.assertTrue(sparse["trend"].get("reason"))

    def test_varying_configured_targets_are_preserved_by_term(self):
        rows = [
            assessment_row(
                indicator_id=1,
                indicator_code="PI-1",
                term_id=term_id,
                term_label=term_label,
                term_order=term_id,
                attainment=attainment,
                target=target,
            )
            for term_id, term_label, attainment, target in (
                (1, "Fall 2023", 68, 65),
                (2, "Spring 2024", 76, 75),
                (3, "Fall 2024", 82, 85),
            )
        ]

        _chart, metadata = self.assert_faceted_chart(rows, panel_count=1)
        self.assertEqual(metadata["target_mode"], "configured_by_term")
        panel = metadata["panels"][0]
        self.assertEqual(panel["target_values"], [65.0, 75.0, 85.0])
        self.assertIn("configured target", panel["target_label"].casefold())

    def test_chart_has_no_confidence_band_artist_or_interval_metadata(self):
        rows = [
            assessment_row(
                indicator_id=indicator_id,
                indicator_code=f"PI-{indicator_id}",
                term_id=term_id,
                term_label=("Fall 2023", "Spring 2024", "Fall 2024")[term_id - 1],
                term_order=term_id,
                attainment=60 + 4 * term_id + indicator_id,
            )
            for indicator_id in (1, 2, 3)
            for term_id in (1, 2, 3)
        ]
        _chart, metadata = self.assert_faceted_chart(rows, panel_count=3)
        forbidden = ("confidence", "conf_int", "ci_lower", "ci_upper", "band")
        for key in recursive_keys(metadata):
            normalized = key.casefold()
            self.assertFalse(
                any(token in normalized for token in forbidden),
                f"Confidence-band metadata is not requested: {key}",
            )

        captured: dict[str, object] = {}

        def capture_chart(figure, **kwargs):
            captured["figure"] = figure
            return kwargs

        with patch.object(analysis_engine, "_chart", side_effect=capture_chart):
            analysis_engine._indicator_chart(analyze_rows(rows), pyplot)
        figure = captured["figure"]
        try:
            shaded_regions = [
                artist
                for axis in figure.axes
                for artist in axis.collections
                if isinstance(artist, PolyCollection)
            ]
            self.assertEqual(
                shaded_regions,
                [],
                "The PI trend view should not draw confidence-band polygons.",
            )
        finally:
            pyplot.close(figure)


class FacultyAssessmentEditingTests(unittest.TestCase):
    """Prove that a real faculty account can sign in, create, and revise drafts."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "faculty-editing-test-secret",
                "DATABASE": str(root / "faculty-editing.db"),
                "UPLOAD_FOLDER": str(root / "uploads"),
            }
        )
        self.client = self.app.test_client()
        self._setup_owner()
        self._create_courses_and_faculty()
        self._login_faculty_and_replace_temporary_password()

    def tearDown(self):
        self.temp.cleanup()

    def csrf(self) -> str:
        with self.client.session_transaction() as session:
            return session["csrf_token"]

    def _setup_owner(self) -> None:
        self.client.get("/setup")
        response = self.client.post(
            "/setup",
            data={
                "csrf_token": self.csrf(),
                "institution": "Faculty Workflow University",
                "program_name": "Mechanical Engineering",
                "program_code": "BSME",
                "full_name": "Program Owner",
                "email": "owner@example.edu",
                "password": "owner-password-long",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.client.get("/login")
        response = self.client.post(
            "/login",
            data={
                "csrf_token": self.csrf(),
                "login": "owner@example.edu",
                "password": "owner-password-long",
            },
        )
        self.assertEqual(response.status_code, 302)

    def _create_courses_and_faculty(self) -> None:
        for code, name in (
            ("MECE 3320", "Measurements and Instrumentation"),
            ("MECE 4350", "Unassigned Capstone"),
        ):
            response = self.client.post(
                "/configuration",
                data={
                    "csrf_token": self.csrf(),
                    "kind": "course",
                    "code": code,
                    "name": name,
                    "description": "Test course",
                },
            )
            self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            db = get_db()
            self.assigned_course_id = db.execute(
                "SELECT id FROM courses WHERE code='MECE 3320'"
            ).fetchone()["id"]
            self.unassigned_course_id = db.execute(
                "SELECT id FROM courses WHERE code='MECE 4350'"
            ).fetchone()["id"]
        response = self.client.post(
            "/users",
            data={
                "csrf_token": self.csrf(),
                "full_name": "Assigned Faculty",
                "username": "assigned.faculty",
                "email": "faculty@example.edu",
                "role": "faculty",
                "temporary_password": "temporary-password",
                "course_ids": str(self.assigned_course_id),
            },
        )
        self.assertEqual(response.status_code, 302)

    def _login_faculty_and_replace_temporary_password(self) -> None:
        self.client.post("/logout", data={"csrf_token": self.csrf()})
        self.client.get("/login")
        response = self.client.post(
            "/login",
            data={
                "csrf_token": self.csrf(),
                "login": "assigned.faculty",
                "password": "temporary-password",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/account/password")
        response = self.client.post(
            "/account/password",
            data={
                "csrf_token": self.csrf(),
                "current_password": "temporary-password",
                "new_password": "faculty-password-long",
                "confirm_password": "faculty-password-long",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.client.get("/login")
        response = self.client.post(
            "/login",
            data={
                "csrf_token": self.csrf(),
                "login": "faculty@example.edu",
                "password": "faculty-password-long",
            },
        )
        self.assertEqual(response.status_code, 302)

    def _dimensions(self) -> dict[str, object]:
        with self.app.app_context():
            db = get_db()
            return {
                "term_id": db.execute("SELECT id FROM academic_terms").fetchone()["id"],
                "outcome_id": db.execute(
                    "SELECT id FROM outcomes ORDER BY display_order LIMIT 1"
                ).fetchone()["id"],
                "indicator_id": db.execute(
                    "SELECT id FROM performance_indicators ORDER BY id LIMIT 1"
                ).fetchone()["id"],
                "rubric_id": db.execute("SELECT id FROM rubrics LIMIT 1").fetchone()["id"],
                "levels": db.execute(
                    "SELECT id FROM rubric_levels ORDER BY display_order"
                ).fetchall(),
            }

    def _assessment_payload(
        self,
        *,
        course_id: int,
        tool: str,
        target: float,
        counts: tuple[int, int, int, int],
    ) -> dict[str, object]:
        dimensions = self._dimensions()
        payload: dict[str, object] = {
            "csrf_token": self.csrf(),
            "term_id": dimensions["term_id"],
            "course_id": course_id,
            "outcome_id": dimensions["outcome_id"],
            "indicator_id": dimensions["indicator_id"],
            "rubric_id": dimensions["rubric_id"],
            "method": "direct",
            "assessment_tool": tool,
            "bloom_level": "Analyze",
            "sample_size": sum(counts),
            "target": target,
            "rationale": "Faculty-selected direct measure",
            "observations": "Faculty interpretation",
            "action_notes": "Faculty improvement action",
        }
        for level, count in zip(dimensions["levels"], counts):
            payload[f"level_{level['id']}"] = count
        return payload

    def test_faculty_can_sign_in_create_and_modify_own_assigned_course_data(self):
        new_form = self.client.get("/assessments/new")
        self.assertEqual(new_form.status_code, 200)
        self.assertIn(b"MECE 3320", new_form.data)
        self.assertNotIn(b"MECE 4350", new_form.data)

        response = self.client.post(
            "/assessments/new",
            data=self._assessment_payload(
                course_id=self.assigned_course_id,
                tool="Original laboratory practical",
                target=70,
                counts=(3, 5, 1, 1),
            ),
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            db = get_db()
            record = db.execute(
                """SELECT ar.*,u.email AS collector_email
                   FROM assessment_records ar JOIN users u ON u.id=ar.collected_by"""
            ).fetchone()
            self.assertEqual(record["collector_email"], "faculty@example.edu")
            self.assertEqual(record["course_id"], self.assigned_course_id)
            self.assertEqual(record["status"], "draft")
            record_id = record["id"]

        edit_payload = self._assessment_payload(
            course_id=self.assigned_course_id,
            tool="Revised laboratory practical",
            target=75,
            counts=(4, 2, 2, 2),
        )
        edit_payload["record_version"] = record["record_version"]
        response = self.client.post(
            f"/assessments/{record_id}/edit",
            data=edit_payload,
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            db = get_db()
            revised = db.execute(
                "SELECT assessment_tool,target,status FROM assessment_records WHERE id=?",
                (record_id,),
            ).fetchone()
            self.assertEqual(revised["assessment_tool"], "Revised laboratory practical")
            self.assertEqual(revised["target"], 75)
            self.assertEqual(revised["status"], "draft")
            result_counts = [
                row["student_count"]
                for row in db.execute(
                    """SELECT student_count FROM assessment_results ar
                       JOIN rubric_levels rl ON rl.id=ar.rubric_level_id
                       WHERE assessment_id=? ORDER BY rl.display_order""",
                    (record_id,),
                )
            ]
            self.assertEqual(result_counts, [4, 2, 2, 2])

        denied = self.client.post(
            f"/assessments/{record_id}/edit",
            data=self._assessment_payload(
                course_id=self.unassigned_course_id,
                tool="Unauthorized reassignment",
                target=70,
                counts=(3, 5, 1, 1),
            ),
        )
        self.assertEqual(denied.status_code, 403)


if __name__ == "__main__":
    unittest.main()
