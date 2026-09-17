from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

import matplotlib
import numpy as np

matplotlib.use("Agg", force=True)

from matplotlib import pyplot
from matplotlib.collections import PolyCollection

from abet_platform import analysis_engine
from abet_platform.analysis_engine import analyze_rows, generate_charts


TERMS = (
    (91, "Fall 2023", 10),
    (17, "Spring 2024", 20),
    (73, "Fall 2024", 30),
    (28, "Spring 2025", 40),
)
TERM_LABELS = [label for _term_id, label, _order in TERMS]


def assessment_row(
    *,
    campus: str,
    term_position: int,
    attainment: float,
    target: float,
    course_id: int = 101,
    course_code: str = "MECE 3315",
    indicator_id: int = 1,
    indicator_code: str = "PI-1",
    bloom_level: str = "Analyze",
    status: str = "approved",
) -> dict[str, object]:
    """Create one unweighted assessment measure for the public engine API."""
    term_id, term_label, term_order = TERMS[term_position]
    return {
        "id": hash(
            (
                campus,
                term_id,
                attainment,
                target,
                course_id,
                indicator_id,
                bloom_level,
                status,
            )
        ),
        "campus": campus,
        "course_id": course_id,
        "course_code": course_code,
        "course_label": f"{course_code} — Test course",
        "term_id": term_id,
        "term_label": term_label,
        "term_order": term_order,
        "outcome_id": 1,
        "outcome_code": "SLO1",
        "outcome_label": "SLO1: Test outcome",
        "outcome_order": 1,
        "indicator_id": indicator_id,
        "indicator_code": indicator_code,
        "indicator_label": f"{indicator_code}: Test indicator",
        "bloom_level": bloom_level,
        "attainment": attainment,
        "target": target,
        "status": status,
    }


def two_campus_rows() -> list[dict[str, object]]:
    """Opposite campus signals with deliberate holes on the shared term axis."""
    rows = [
        # Edinburg rises and has no Fall 2024 observation.
        assessment_row(campus="Edinburg", term_position=0, attainment=60, target=70),
        assessment_row(campus="Edinburg", term_position=1, attainment=72, target=71),
        assessment_row(campus="Edinburg", term_position=3, attainment=90, target=76),
        # Brownsville falls and has no Spring 2024 observation.
        assessment_row(campus="Brownsville", term_position=0, attainment=88, target=80),
        assessment_row(campus="Brownsville", term_position=2, attainment=76, target=78),
        assessment_row(campus="Brownsville", term_position=3, attainment=66, target=65),
    ]
    # Deliberately scramble the input. Chronology must come from term_order, not
    # row order or the non-monotonic term primary keys above.
    return [rows[index] for index in (5, 1, 3, 0, 4, 2)]


def series_map(container: dict[str, object]) -> dict[str, dict[str, object]]:
    series = container.get("campus_series")
    if not isinstance(series, list):
        raise AssertionError("Accessible metadata must contain a campus_series list.")
    return {str(item["campus"]): item for item in series}


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


class CampusSeriesAssertions:
    def assert_two_campus_series(self, container: dict[str, object]) -> None:
        raw_series = container.get("campus_series")
        self.assertIsInstance(raw_series, list)
        self.assertEqual(
            [item["campus"] for item in raw_series],
            ["Edinburg", "Brownsville"],
            "Campus series must use the stable UTRGV display order.",
        )
        by_campus = series_map(container)
        expected = {
            "Edinburg": {
                "attainment_values": [60.0, 72.0, None, 90.0],
                "target_values": [70.0, 71.0, None, 76.0],
                "segments": [[0, 1], [3]],
            },
            "Brownsville": {
                "attainment_values": [88.0, None, 76.0, 66.0],
                "target_values": [80.0, None, 78.0, 65.0],
                "segments": [[0], [2, 3]],
            },
        }
        for campus, values in expected.items():
            series = by_campus[campus]
            self.assertEqual(series["term_labels"], TERM_LABELS)
            self.assertEqual(series["attainment_values"], values["attainment_values"])
            self.assertEqual(series["target_values"], values["target_values"])
            segments = series.get("segments")
            self.assertIsInstance(segments, list)
            self.assertEqual(
                [segment["term_indices"] for segment in segments],
                values["segments"],
            )
            self.assertEqual(
                [segment["term_labels"] for segment in segments],
                [
                    [TERM_LABELS[index] for index in indices]
                    for indices in values["segments"]
                ],
            )
            self.assertEqual(series["measure_count"], 3)
            self.assertTrue(series["style"].get("color"))
            self.assertTrue(series["style"].get("marker"))
            self.assertTrue(series["style"].get("linestyle"))
            trend = series.get("trend")
            self.assertIsInstance(trend, dict)
            self.assertEqual(trend.get("status"), "available")
            self.assertIsInstance(trend.get("slope"), float)
            self.assertIsNone(trend.get("reason"))
        self.assertGreater(by_campus["Edinburg"]["trend"]["slope"], 0)
        self.assertLess(by_campus["Brownsville"]["trend"]["slope"], 0)
        self.assertNotEqual(
            by_campus["Edinburg"]["style"]["color"],
            by_campus["Brownsville"]["style"]["color"],
        )


class CampusLongitudinalAnalysisTests(CampusSeriesAssertions, unittest.TestCase):
    maxDiff = None

    def test_analysis_exposes_separate_target_aware_campus_trends(self):
        analysis = analyze_rows(two_campus_rows())

        self.assertEqual([term["label"] for term in analysis["terms"]], TERM_LABELS)
        campus_trends = analysis.get("campus_trends")
        self.assertIsInstance(campus_trends, list)
        self.assert_two_campus_series({"campus_series": campus_trends})

        # The compatibility aggregate is allowed to remain, but it must not be
        # the only longitudinal statistic when the two campuses point in
        # opposite directions.
        self.assertIn("trend", analysis)
        methodology = str(analysis["methodology"].get("longitudinal_analysis"))
        self.assertIn("Edinburg", methodology)
        self.assertIn("Brownsville", methodology)
        self.assertIn("separate", methodology.casefold())
        self.assertIn("missing", methodology.casefold())

    def test_utrgv_template_and_engine_use_the_same_campus_trend_shape(self):
        """Guard against Jinja silently treating missing dictionary keys as blank."""
        series = analyze_rows(two_campus_rows())["campus_trends"][0]
        template = (
            Path(__file__).resolve().parents[1]
            / "abet_platform"
            / "templates"
            / "analytics.html"
        ).read_text(encoding="utf-8")

        if "campus_trend.slope" in template:
            for key in (
                "slope",
                "direction",
                "term_count",
                "r_squared",
                "p_value",
                "reason",
            ):
                self.assertIn(
                    key,
                    series,
                    f"The template reads campus_trend.{key}, but the engine omits it.",
                )
        if "campus_trend.terms" in template:
            self.assertIn(
                "terms",
                series,
                "The template loops campus_trend.terms, but the engine omits it.",
            )
        if "campus_trend.trend.slope" in template:
            self.assertIn("slope", series["trend"])

    def test_single_campus_and_sparse_series_are_explicit_not_errors(self):
        rows = [
            assessment_row(
                campus="Edinburg",
                term_position=2,
                attainment=81,
                target=75,
            )
        ]
        analysis = analyze_rows(rows)
        trends = analysis.get("campus_trends")
        self.assertIsInstance(trends, list)
        self.assertEqual([item["campus"] for item in trends], ["Edinburg"])
        series = trends[0]
        self.assertEqual(series["term_labels"], ["Fall 2024"])
        self.assertEqual(series["attainment_values"], [81.0])
        self.assertEqual(series["target_values"], [75.0])
        self.assertEqual(series["segments"][0]["term_indices"], [0])
        self.assertEqual(series["trend"]["status"], "unavailable")
        self.assertIsNone(series["trend"]["slope"])
        self.assertTrue(series["trend"]["reason"])
        charts = generate_charts(rows)
        for chart_name in ("trend_line", "semester_course", "semester_indicator"):
            chart = charts[chart_name]
            self.assertTrue(
                chart["available"],
                f"{chart_name} should retain the observed point even when a fitted trend is unavailable.",
            )
            self.assertIn("Edinburg", chart["alt_text"])
            self.assertNotIn("Brownsville", chart["alt_text"])

    def test_selected_course_filter_cannot_leak_another_course_into_series(self):
        selected_rows = two_campus_rows()
        excluded_rows = [
            assessment_row(
                campus=campus,
                term_position=position,
                attainment=5,
                target=95,
                course_id=202,
                course_code="MECE 4350",
                indicator_id=2,
                indicator_code="PI-2",
            )
            for campus in ("Edinburg", "Brownsville")
            for position in range(4)
        ]
        analysis = analyze_rows(selected_rows + excluded_rows, selected_courses=[101])
        self.assertEqual(analysis["selected_courses"], [101])
        self.assertEqual({row["course_id"] for row in analysis["rows"]}, {101})
        self.assert_two_campus_series({"campus_series": analysis["campus_trends"]})

        charts = generate_charts(selected_rows + excluded_rows, selected_courses=[101])
        searchable = json.dumps(charts, sort_keys=True)
        self.assertNotIn("MECE 4350", searchable)
        self.assertNotIn('"attainment_values": [5.0', searchable)


class CampusLongitudinalChartTests(CampusSeriesAssertions, unittest.TestCase):
    def _capture(
        self,
        function,
        rows: list[dict[str, object]],
    ) -> tuple[dict[str, object], object]:
        captured: dict[str, object] = {}

        def capture_chart(figure, **kwargs):
            captured["figure"] = figure
            captured.update(kwargs)
            return kwargs

        with patch.object(analysis_engine, "_chart", side_effect=capture_chart):
            function(analyze_rows(rows), pyplot)
        self.assertIn("figure", captured)
        return captured, captured["figure"]

    def assert_no_confidence_band(self, chart_metadata, figure) -> None:
        forbidden = ("confidence", "conf_int", "ci_lower", "ci_upper", "band")
        for key in recursive_keys(chart_metadata):
            normalized = key.casefold()
            self.assertFalse(
                any(token in normalized for token in forbidden),
                f"Confidence-band metadata is not part of this chart contract: {key}",
            )
        shaded = [
            artist
            for axis in figure.axes
            for artist in axis.collections
            if isinstance(artist, PolyCollection)
        ]
        self.assertEqual(shaded, [], "Campus trend charts must not draw confidence bands.")

    def assert_observed_lines_do_not_bridge_term_gaps(self, figure) -> None:
        segmented_lines = [
            line
            for axis in figure.axes
            for line in axis.lines
            if any(
                token in str(line.get_label()).casefold()
                for token in ("observed", "target path")
            )
        ]
        # The fixture has one multi-point observed and target run per campus.
        self.assertGreaterEqual(len(segmented_lines), 4)
        for line in segmented_lines:
            x_values = np.asarray(line.get_xdata(), dtype=float)
            y_values = np.asarray(line.get_ydata(), dtype=float)
            for left, right in zip(range(len(x_values) - 1), range(1, len(x_values))):
                if not (np.isfinite(y_values[left]) and np.isfinite(y_values[right])):
                    continue
                self.assertLessEqual(
                    x_values[right] - x_values[left],
                    1.0,
                    f"Observed line {line.get_label()} bridges a term with no evidence.",
                )

    def assert_separate_fitted_lines(self, figure) -> None:
        lines = [
            line
            for axis in figure.axes
            for line in axis.lines
        ]
        labels = {str(line.get_label()) for line in lines}
        for campus in ("Edinburg", "Brownsville"):
            label = f"{campus} fitted trend"
            self.assertIn(
                label,
                labels,
                f"The available {campus} regression must have its own fitted line.",
            )
            fitted_lines = [line for line in lines if str(line.get_label()) == label]
            fitted_x = np.concatenate(
                [np.asarray(line.get_xdata(), dtype=float) for line in fitted_lines]
            )
            self.assertEqual(float(np.min(fitted_x)), 0.0)
            self.assertEqual(
                float(np.max(fitted_x)),
                3.0,
                "A fitted regression should span the campus's first through latest "
                "observed term; only observed paths break at missing terms.",
            )

    def test_overall_chart_uses_two_observed_and_two_fitted_campus_series(self):
        captured, figure = self._capture(analysis_engine._trend_chart, two_campus_rows())
        try:
            self.assertEqual(captured.get("chart_type"), "campus_trend")
            self.assert_two_campus_series(captured["metadata"])
            text = " ".join(
                [
                    str(captured.get("title")),
                    str(captured.get("alt_text")),
                    *(str(item) for item in captured.get("insights", [])),
                ]
            )
            for concept in ("Edinburg", "Brownsville", "configured target"):
                self.assertIn(concept.casefold(), text.casefold())
            self.assertNotIn("mean target", text.casefold())
            self.assert_observed_lines_do_not_bridge_term_gaps(figure)
            self.assert_separate_fitted_lines(figure)
            self.assert_no_confidence_band(captured["metadata"], figure)
        finally:
            pyplot.close(figure)

    def test_course_term_chart_is_faceted_and_never_pools_course_campus_cells(self):
        captured, figure = self._capture(
            analysis_engine._semester_course_chart,
            two_campus_rows(),
        )
        try:
            self.assertEqual(captured.get("chart_type"), "faceted_course_trend")
            metadata = captured["metadata"]
            self.assertEqual(metadata["facet_by"], "course")
            self.assertEqual(metadata["panel_count"], 1)
            panel = metadata["panels"][0]
            self.assertEqual(panel["course_code"], "MECE 3315")
            self.assert_two_campus_series(panel)
            self.assert_observed_lines_do_not_bridge_term_gaps(figure)
            self.assert_separate_fitted_lines(figure)
            self.assert_no_confidence_band(metadata, figure)
        finally:
            pyplot.close(figure)

    def test_pi_bloom_chart_combines_pi_blocks_but_keeps_campus_series_separate(self):
        captured, figure = self._capture(analysis_engine._indicator_chart, two_campus_rows())
        try:
            self.assertEqual(captured.get("chart_type"), "combined_pi_trend")
            self.assertEqual(len(figure.axes), 1)
            metadata = captured["metadata"]
            self.assertEqual(metadata["layout"], "single_axis_pi_blocks")
            self.assertEqual(metadata["panel_count"], 1)
            panel = metadata["panels"][0]
            self.assertEqual(panel["indicator_code"], "PI-1")
            self.assert_two_campus_series(panel)
            line_labels = {
                str(line.get_label()) for line in figure.axes[0].lines
            }
            self.assertFalse(
                any(
                    token in label.casefold()
                    for label in line_labels
                    for token in ("observed", "segment", "target")
                )
            )
            self.assertEqual(
                line_labels,
                {
                    "PI-1 · Edinburg fitted trend",
                    "PI-1 · Brownsville fitted trend",
                },
            )
            self.assert_no_confidence_band(metadata, figure)
            alt = str(captured["alt_text"])
            self.assertIn("Edinburg", alt)
            self.assertIn("Brownsville", alt)
            visible_legend_labels = {
                label.get_text()
                for legend in figure.legends
                for label in legend.get_texts()
            }
            self.assertIn(
                "Analyze",
                visible_legend_labels,
                "The rendered PI/Bloom figure must visibly map Bloom marker shapes "
                "to their level names, not expose that mapping only in metadata.",
            )
        finally:
            pyplot.close(figure)

    def test_pooled_non_time_charts_disclose_that_both_campuses_are_combined(self):
        charts = generate_charts(two_campus_rows())
        for chart_name in (
            "course_attainment",
            "bloom_boxplot",
            "course_outcome_heatmap",
        ):
            chart = charts[chart_name]
            self.assertTrue(chart["available"], chart.get("reason"))
            text = " ".join(
                [
                    str(chart.get("title")),
                    str(chart.get("alt_text")),
                    *(str(item) for item in chart.get("insights") or []),
                    json.dumps(chart.get("metadata"), sort_keys=True),
                ]
            )
            self.assertIn("combined", text.casefold(), chart_name)
            self.assertIn("Edinburg", text, chart_name)
            self.assertIn("Brownsville", text, chart_name)


if __name__ == "__main__":
    unittest.main()
