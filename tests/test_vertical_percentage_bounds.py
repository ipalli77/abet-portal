from __future__ import annotations

import unittest
from unittest.mock import patch

import matplotlib
import numpy as np

matplotlib.use("Agg", force=True)

from matplotlib import pyplot
from matplotlib.collections import LineCollection, PathCollection

from abet_platform import analysis_engine
from abet_platform.analysis_engine import analyze_rows


TERMS = (
    (11, "Fall 2023", 10),
    (22, "Spring 2024", 20),
    (33, "Fall 2024", 30),
)


def percentage_rows(*, campus_aware: bool) -> list[dict[str, object]]:
    campuses: tuple[str | None, ...] = (
        ("Edinburg", "Brownsville") if campus_aware else (None,)
    )
    rows: list[dict[str, object]] = []
    for campus in campuses:
        for term_id, term_label, term_order in TERMS:
            row: dict[str, object] = {
                "course_id": 101,
                "course_code": "MECE 3315",
                "course_label": "MECE 3315 — Test course",
                "term_id": term_id,
                "term_label": term_label,
                "term_order": term_order,
                "outcome_id": 1,
                "outcome_code": "SLO1",
                "outcome_label": "SLO1: Test outcome",
                "outcome_order": 1,
                "indicator_id": 1,
                "indicator_code": "PI-1",
                "indicator_label": "PI-1: Test indicator",
                "bloom_level": "Apply",
                "attainment": 100.0,
                "target": 100.0,
                "status": "approved",
            }
            if campus is not None:
                row["campus"] = campus
            rows.append(row)
    return rows


def artist_y_values(axis, *, target: bool) -> list[float]:
    values: list[float] = []
    for artist in [*axis.lines, *axis.collections]:
        label_is_target = (
            "target" in str(artist.get_label()).casefold()
            or isinstance(artist, LineCollection)
        )
        if label_is_target != target:
            continue
        if isinstance(artist, PathCollection):
            points = np.asarray(artist.get_offsets(), dtype=float)
            values.extend(float(y_value) for _x_value, y_value in points)
        elif isinstance(artist, LineCollection):
            values.extend(
                float(y_value)
                for segment in artist.get_segments()
                for _x_value, y_value in np.asarray(segment, dtype=float)
            )
        elif hasattr(artist, "get_ydata"):
            values.extend(
                float(value)
                for value in np.asarray(artist.get_ydata(), dtype=float).ravel()
                if np.isfinite(value)
            )
    return values


class VerticalPercentageBoundsTests(unittest.TestCase):
    def capture_chart(self, chart_function, analysis):
        captured: dict[str, object] = {}

        def capture(figure, **kwargs):
            captured["figure"] = figure
            captured.update(kwargs)
            return kwargs

        with patch.object(analysis_engine, "_chart", side_effect=capture):
            chart_function(analysis, pyplot)
        self.assertIn("figure", captured, "The percentage chart was unavailable.")
        figure = captured["figure"]
        self.addCleanup(pyplot.close, figure)
        return figure

    def test_all_vertical_percentage_charts_leave_headroom_above_100_percent(self):
        campus_analysis = analyze_rows(percentage_rows(campus_aware=True))
        generic_analysis = analyze_rows(percentage_rows(campus_aware=False))
        cases = (
            (
                "campus semester-course trend",
                analysis_engine._semester_course_chart,
                campus_analysis,
            ),
            ("Bloom distribution", analysis_engine._bloom_chart, campus_analysis),
            (
                "generic indicator chart",
                analysis_engine._indicator_chart_overall,
                generic_analysis,
            ),
            (
                "combined campus PI chart",
                analysis_engine._indicator_chart,
                campus_analysis,
            ),
            (
                "generic overall trend",
                analysis_engine._trend_chart_overall,
                generic_analysis,
            ),
            (
                "campus trend",
                analysis_engine._trend_chart,
                campus_analysis,
            ),
        )

        for label, chart_function, analysis in cases:
            with self.subTest(chart=label):
                figure = self.capture_chart(chart_function, analysis)
                self.assertTrue(figure.axes)
                for axis in figure.axes:
                    self.assertAlmostEqual(axis.get_ylim()[1], 110.0)

                observed_values = [
                    value
                    for axis in figure.axes
                    for value in artist_y_values(axis, target=False)
                ]
                target_values = [
                    value
                    for axis in figure.axes
                    for value in artist_y_values(axis, target=True)
                ]
                self.assertTrue(
                    any(np.isclose(value, 100.0) for value in observed_values),
                    f"{label} did not render its 100% evidence within the axes.",
                )
                self.assertTrue(
                    any(np.isclose(value, 100.0) for value in target_values),
                    f"{label} did not render its 100% target within the axes.",
                )


if __name__ == "__main__":
    unittest.main()
