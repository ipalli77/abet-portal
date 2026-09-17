from __future__ import annotations

import unittest

from abet_platform.analysis_engine import generate_charts


def assessment_row(
    *,
    course_id: int,
    course_code: str,
    term_id: int,
    term_label: str,
    term_order: int,
    attainment: float,
    target: float,
    indicator_id: int = 1,
    indicator_code: str = "PI-1",
    bloom_level: str = "Analyze",
) -> dict[str, object]:
    """Build the minimum realistic row consumed by the public chart API."""
    return {
        "course_id": course_id,
        "course_code": course_code,
        "course_label": f"{course_code} — Test course {course_id}",
        "term_id": term_id,
        "term_label": term_label,
        "term_order": term_order,
        "outcome_id": 1,
        "outcome_code": "SLO1",
        "outcome_label": "SLO1: Test outcome",
        "outcome_order": 1,
        "indicator_id": indicator_id,
        "indicator_code": indicator_code,
        "bloom_level": bloom_level,
        "attainment": attainment,
        "target": target,
        "status": "approved",
    }


class ClearLongitudinalChartTests(unittest.TestCase):
    """Regression tests for the two formerly crowded longitudinal plots.

    The PNG itself is intentionally not pixel-tested.  The artifact's title,
    alternative text, and insight metadata form the stable, accessible contract
    that explains exactly what the visualization is meant to communicate.
    """

    def assert_clear_artifact(self, chart: dict[str, object], *concepts: str) -> str:
        self.assertTrue(chart["available"], chart.get("reason"))
        self.assertEqual(chart.get("chart_type"), "target_gap_heatmap")
        self.assertTrue(str(chart["data_uri"]).startswith("data:image/png;base64,"))
        self.assertIsNone(chart["reason"])

        insights = chart.get("insights")
        self.assertIsInstance(insights, list)
        self.assertTrue(insights, "The chart should state its main finding in plain language.")
        self.assertTrue(all(isinstance(item, str) and item.strip() for item in insights))

        text = " ".join(
            [str(chart["title"]), str(chart["alt_text"]), *(str(item) for item in insights)]
        )
        for concept in concepts:
            self.assertIn(concept.casefold(), text.casefold())
        return text

    def test_course_term_chart_is_target_relative_and_calls_out_missing_evidence(self):
        rows = [
            assessment_row(
                course_id=101,
                course_code="ME 101",
                term_id=1,
                term_label="Fall 2024",
                term_order=1,
                attainment=84,
                target=70,
            ),
            assessment_row(
                course_id=101,
                course_code="ME 101",
                term_id=2,
                term_label="Spring 2025",
                term_order=2,
                attainment=64,
                target=75,
            ),
            assessment_row(
                course_id=202,
                course_code="ME 202",
                term_id=2,
                term_label="Spring 2025",
                term_order=2,
                attainment=79,
                target=80,
            ),
            assessment_row(
                course_id=202,
                course_code="ME 202",
                term_id=3,
                term_label="Fall 2025",
                term_order=3,
                attainment=91,
                target=85,
            ),
        ]

        chart = generate_charts(rows)["semester_course"]
        text = self.assert_clear_artifact(chart, "course", "term", "target")

        # A 2-course x 3-term matrix has two deliberately absent intersections.
        # The accessible explanation must make that sparsity explicit rather than
        # implying continuity by joining non-adjacent observations with a line.
        self.assertRegex(text.casefold(), r"(2\s+(missing|without|no[- ]evidence)|4\s+of\s+6)")
        self.assertRegex(text.casefold(), r"2\s+of\s+4[^.]{0,40}(met|meet)")
        self.assertRegex(text.casefold(), r"(gap|above|below|met|missed)")

    def test_course_term_cell_uses_its_own_configured_targets_not_a_global_line(self):
        rows = [
            # Same cell: mean attainment 75, mean configured target 70, gap +5.
            assessment_row(
                course_id=101,
                course_code="ME 101",
                term_id=1,
                term_label="Fall 2024",
                term_order=1,
                attainment=84,
                target=80,
            ),
            assessment_row(
                course_id=101,
                course_code="ME 101",
                term_id=1,
                term_label="Fall 2024",
                term_order=1,
                attainment=66,
                target=60,
            ),
            # This cell is above the selection-wide mean target (75) but eight
            # points below its own configured target.  A global line mislabels it.
            assessment_row(
                course_id=101,
                course_code="ME 101",
                term_id=2,
                term_label="Spring 2025",
                term_order=2,
                attainment=82,
                target=90,
            ),
            assessment_row(
                course_id=202,
                course_code="ME 202",
                term_id=1,
                term_label="Fall 2024",
                term_order=1,
                attainment=72,
                target=70,
            ),
        ]

        chart = generate_charts(rows)["semester_course"]
        text = self.assert_clear_artifact(chart, "configured target")

        # The most important exception should be visible in the text contract:
        # ME 101 / Spring 2025 is 82 against 90, i.e. 8 points below target.
        self.assertIn("ME 101", text)
        self.assertIn("Spring 2025", text)
        self.assertRegex(text, r"90(?:\.0)?%?")
        self.assertRegex(text.casefold(), r"(8(?:\.0)?\s+(percentage\s+)?points?\s+below|gap\s*[-−]\s*8(?:\.0)?)")

    def test_sparse_course_term_matrix_does_not_invent_intermediate_values(self):
        rows = [
            assessment_row(
                course_id=101,
                course_code="ME 101",
                term_id=1,
                term_label="Fall 2024",
                term_order=1,
                attainment=88,
                target=75,
            ),
            assessment_row(
                course_id=202,
                course_code="ME 202",
                term_id=3,
                term_label="Fall 2025",
                term_order=3,
                attainment=62,
                target=70,
            ),
            # Establish the middle term without filling either focal course's
            # intermediate cell.
            assessment_row(
                course_id=303,
                course_code="ME 303",
                term_id=2,
                term_label="Spring 2025",
                term_order=2,
                attainment=77,
                target=70,
            ),
        ]

        chart = generate_charts(rows)["semester_course"]
        text = self.assert_clear_artifact(chart, "evidence")

        # Three observations in a 3x3 matrix means six explicit no-evidence cells.
        self.assertRegex(text.casefold(), r"(6\s+(missing|without|no[- ]evidence)|3\s+of\s+9)")
        self.assertNotRegex(text.casefold(), r"interpolat(ed|ion)")

    def test_dense_indicator_bloom_selection_uses_readable_facets(self):
        rows = []
        levels = ("Understand", "Apply", "Analyze", "Evaluate", "Create")
        for indicator_id in range(1, 14):
            # Thirteen distinct indicator/Bloom series intentionally exceeds the
            # previous hard stop at twelve series.
            rows.append(
                assessment_row(
                    course_id=101,
                    course_code="ME 101",
                    term_id=(indicator_id % 3) + 1,
                    term_label=("Fall 2024", "Spring 2025", "Fall 2025")[indicator_id % 3],
                    term_order=(indicator_id % 3) + 1,
                    attainment=60 + indicator_id,
                    target=70 + (indicator_id % 2) * 5,
                    indicator_id=indicator_id,
                    indicator_code=f"PI-{indicator_id}",
                    bloom_level=levels[indicator_id % len(levels)],
                )
            )

        chart = generate_charts(rows)["semester_indicator"]
        self.assertTrue(chart["available"], chart.get("reason"))
        self.assertEqual(chart.get("chart_type"), "faceted_pi_trend")
        text = " ".join(
            [
                str(chart["title"]),
                str(chart["alt_text"]),
                *(str(item) for item in chart["insights"]),
            ]
        )
        for concept in ("indicator", "Bloom", "term", "target"):
            self.assertIn(concept.casefold(), text.casefold())

        # Dense selections remain useful, with one panel per indicator rather
        # than a long overlaid legend or the former 12-series hard stop.
        self.assertNotIn("no more than 12", text.casefold())
        self.assertRegex(text.casefold(), r"13\s+(performance-)?indicator")
        self.assertRegex(text.casefold(), r"(26\s+(missing|without|no[- ]evidence)|13\s+of\s+39)")


if __name__ == "__main__":
    unittest.main()
