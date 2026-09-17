from __future__ import annotations

import unittest
from unittest.mock import patch

import matplotlib
import numpy as np

matplotlib.use("Agg", force=True)

from matplotlib import pyplot
from matplotlib import colors as mcolors
from matplotlib.collections import PathCollection, PolyCollection

from abet_platform import analysis_engine
from abet_platform.analysis_engine import analyze_rows


TERMS = (
    (301, "Fall 2023", 10),
    (102, "Spring 2024", 20),
    (909, "Fall 2024", 30),
)
TERM_LABELS = [label for _term_id, label, _order in TERMS]
SHORT_TERM_LABELS = ["F23", "Sp24", "F24"]


def assessment_row(
    *,
    campus: str,
    indicator_id: int,
    indicator_code: str,
    term_position: int,
    attainment: float,
    target: float,
    bloom_level: str,
) -> dict[str, object]:
    term_id, term_label, term_order = TERMS[term_position]
    return {
        "campus": campus,
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
        "indicator_id": indicator_id,
        "indicator_code": indicator_code,
        "indicator_label": f"{indicator_code}: Test indicator",
        "bloom_level": bloom_level,
        "attainment": attainment,
        "target": target,
        "status": "approved",
    }


def combined_pi_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    dense = {
        "PI-1": {
            "id": 1,
            "Edinburg": ((64, 61), (74, 72), (86, 83)),
            "Brownsville": ((88, 91), (77, 78), (66, 63)),
        },
        "PI-2": {
            "id": 2,
            "Edinburg": ((58, 60), (70, 69), (82, 81)),
            "Brownsville": ((91, 86), (80, 82), (69, 74)),
        },
    }
    bloom_levels = ("Understand", "Apply", "Analyze")
    for indicator_code, values in dense.items():
        for campus in ("Edinburg", "Brownsville"):
            for term_position, (attainment, target) in enumerate(values[campus]):
                rows.append(
                    assessment_row(
                        campus=campus,
                        indicator_id=int(values["id"]),
                        indicator_code=indicator_code,
                        term_position=term_position,
                        attainment=attainment,
                        target=target,
                        bloom_level=bloom_levels[term_position],
                    )
                )
    # PI-10 proves natural code ordering and sparse-block behavior. Each campus
    # contributes one point in a different term, so the block must remain
    # visible without receiving an invented observed connection or fitted line.
    rows.extend(
        [
            assessment_row(
                campus="Edinburg",
                indicator_id=10,
                indicator_code="PI-10",
                term_position=0,
                attainment=54,
                target=62,
                bloom_level="Evaluate",
            ),
            assessment_row(
                campus="Brownsville",
                indicator_id=10,
                indicator_code="PI-10",
                term_position=2,
                attainment=68,
                target=73,
                bloom_level="Create",
            ),
        ]
    )
    # Input order must not determine PI or term order.
    order = (13, 7, 2, 10, 0, 12, 5, 1, 9, 3, 11, 4, 8, 6)
    return [rows[index] for index in order]


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


class CombinedPiTrendChartTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.rows = combined_pi_rows()
        self.analysis = analyze_rows(self.rows)
        self.captured: dict[str, object] = {}

        def capture_chart(figure, **kwargs):
            self.captured["figure"] = figure
            self.captured.update(kwargs)
            return kwargs

        with patch.object(analysis_engine, "_chart", side_effect=capture_chart):
            analysis_engine._indicator_chart(self.analysis, pyplot)
        self.figure = self.captured["figure"]
        self.metadata = self.captured["metadata"]

    def tearDown(self):
        pyplot.close(self.figure)

    @property
    def axis(self):
        self.assertEqual(
            len(self.figure.axes),
            1,
            "UTRGV PI trends must share one axes instead of returning to PI facets.",
        )
        return self.figure.axes[0]

    def panels(self) -> list[dict[str, object]]:
        panels = self.metadata.get("panels")
        self.assertIsInstance(panels, list)
        return panels

    def test_one_axis_contains_naturally_ordered_pi_blocks_and_repeated_terms(self):
        self.assertEqual(self.captured.get("chart_type"), "combined_pi_trend")
        self.assertEqual(self.metadata.get("layout"), "single_axis_pi_blocks")
        self.assertEqual(self.metadata.get("axis_count"), 1)
        self.assertEqual(self.metadata.get("panel_count"), 3)
        panels = self.panels()
        self.assertEqual(self.metadata.get("pi_blocks"), panels)
        self.assertEqual(
            [panel["indicator_code"] for panel in panels],
            ["PI-1", "PI-2", "PI-10"],
        )
        self.assertEqual(
            [panel["block_index"] for panel in panels],
            [0, 1, 2],
        )
        self.assertEqual(
            self.metadata.get("x_tick_labels"),
            TERM_LABELS * 3,
        )
        self.assertEqual(
            self.metadata.get("x_tick_display_labels"),
            SHORT_TERM_LABELS * 3,
        )
        self.assertEqual(
            [label.get_text() for label in self.axis.get_xticklabels()],
            SHORT_TERM_LABELS * 3,
        )

        prior_end = -np.inf
        all_positions: list[float] = []
        for panel in panels:
            self.assertEqual(panel["term_labels"], TERM_LABELS)
            positions = panel["x_positions"]
            self.assertEqual(len(positions), len(TERMS))
            self.assertEqual(positions, sorted(positions))
            self.assertGreater(positions[0], prior_end)
            prior_end = positions[-1]
            self.assertEqual(panel["x_start"], positions[0])
            self.assertEqual(panel["x_end"], positions[-1])
            all_positions.extend(positions)
        self.assertEqual(self.metadata.get("x_tick_positions"), all_positions)
        self.assertEqual(
            list(self.metadata.get("campus_x_offsets")),
            ["Edinburg", "Brownsville"],
        )
        self.assertNotEqual(
            self.metadata["campus_x_offsets"]["Edinburg"],
            self.metadata["campus_x_offsets"]["Brownsville"],
        )
        display_width = self.metadata.get("display_width_px")
        self.assertIsInstance(display_width, int)
        self.assertGreaterEqual(display_width, 800)
        self.assertLessEqual(display_width, 2400)

        visible_text = [item.get_text() for item in self.axis.texts]
        header_positions = [
            next(index for index, text in enumerate(visible_text) if code in text)
            for code in ("PI-1", "PI-2", "PI-10")
        ]
        self.assertEqual(header_positions, sorted(header_positions))

    def test_observations_are_scatter_only_and_each_dense_block_has_two_fits(self):
        axis = self.axis
        self.assertTrue(
            any(isinstance(artist, PathCollection) for artist in axis.collections),
            "Observed campus/Bloom symbols must be scatter artists.",
        )
        lines = list(axis.lines)
        labels = [str(line.get_label()) for line in lines]
        self.assertFalse(
            any(
                token in label.casefold()
                for label in labels
                for token in ("observed", "segment", "target")
            ),
            "Observed attainment symbols must never be connected with a line.",
        )
        for line in lines:
            label = str(line.get_label()).casefold()
            self.assertIn(
                "fitted trend",
                label,
                f"Only fitted models may be Line2D artists; found {line.get_label()!r}.",
            )

        target_collections = [
            artist
            for artist in axis.collections
            if "target" in str(artist.get_label()).casefold()
        ]
        self.assertTrue(
            target_collections,
            "Every observed PI-campus-term value needs a target scatter marker.",
        )
        self.assertEqual(
            sum(len(artist.get_offsets()) for artist in target_collections),
            14,
            "Targets must retain all 14 campus/PI/term observations without pooling.",
        )
        for artist in target_collections:
            self.assertIsInstance(artist, PathCollection)
            paths = artist.get_paths()
            self.assertTrue(paths)
            vertices = np.asarray(paths[0].vertices, dtype=float)
            self.assertGreater(float(np.ptp(vertices[:, 0])), 0.0)
            self.assertAlmostEqual(
                float(np.ptp(vertices[:, 1])),
                0.0,
                places=12,
                msg="Configured targets must use underscore scatter markers.",
            )

        panels = {panel["indicator_code"]: panel for panel in self.panels()}
        expected_fit_labels = {
            f"{indicator} · {campus} fitted trend"
            for indicator in ("PI-1", "PI-2")
            for campus in ("Edinburg", "Brownsville")
        }
        actual_fit_labels = {
            label for label in labels if "fitted trend" in label.casefold()
        }
        self.assertEqual(actual_fit_labels, expected_fit_labels)
        self.assertFalse(any(label.startswith("PI-10 ·") for label in labels))

        for label in expected_fit_labels:
            indicator, remainder = label.split(" · ", 1)
            campus = remainder.removesuffix(" fitted trend")
            line = next(line for line in lines if str(line.get_label()) == label)
            positions = panels[indicator]["x_positions"]
            offset = self.metadata["campus_x_offsets"][campus]
            x_values = np.asarray(line.get_xdata(), dtype=float)
            self.assertAlmostEqual(
                float(np.min(x_values)),
                float(positions[0] + offset),
            )
            self.assertAlmostEqual(
                float(np.max(x_values)),
                float(positions[-1] + offset),
            )

    def test_targets_remain_campus_term_specific_and_sparse_pi_stays_visible(self):
        panels = {panel["indicator_code"]: panel for panel in self.panels()}
        pi1 = {
            series["campus"]: series for series in panels["PI-1"]["campus_series"]
        }
        self.assertEqual(pi1["Edinburg"]["target_values"], [61.0, 72.0, 83.0])
        self.assertEqual(pi1["Brownsville"]["target_values"], [91.0, 78.0, 63.0])
        self.assertNotEqual(
            pi1["Edinburg"]["target_values"],
            pi1["Brownsville"]["target_values"],
        )
        self.assertEqual(self.metadata.get("target_mode"), "configured_by_campus_and_term")

        sparse = panels["PI-10"]
        self.assertGreater(sparse["point_count"], 0)
        sparse_series = {
            series["campus"]: series for series in sparse["campus_series"]
        }
        self.assertEqual(sparse_series["Edinburg"]["attainment_values"], [54.0, None, None])
        self.assertEqual(sparse_series["Brownsville"]["attainment_values"], [None, None, 68.0])
        for series in sparse_series.values():
            self.assertEqual(series["trend"]["status"], "unavailable")
            self.assertIsNone(series["trend"]["slope"])
            self.assertTrue(series["trend"]["reason"])

        scatter_offsets = np.concatenate(
            [
                np.asarray(artist.get_offsets(), dtype=float)
                for artist in self.axis.collections
                if isinstance(artist, PathCollection)
                and len(artist.get_offsets())
            ]
        )
        sparse_positions = sparse["x_positions"]
        expected_sparse_points = (
            (
                sparse_positions[0] + self.metadata["campus_x_offsets"]["Edinburg"],
                54.0,
            ),
            (
                sparse_positions[2] + self.metadata["campus_x_offsets"]["Brownsville"],
                68.0,
            ),
        )
        for expected_x, expected_y in expected_sparse_points:
            self.assertTrue(
                any(
                    np.isclose(x_value, expected_x)
                    and np.isclose(y_value, expected_y)
                    for x_value, y_value in scatter_offsets
                ),
                f"Sparse PI-10 observation ({expected_x}, {expected_y}) is not visible.",
            )

        alt = str(self.captured.get("alt_text"))
        for concept in ("single", "PI-10", "Edinburg", "Brownsville", "target"):
            self.assertIn(concept.casefold(), alt.casefold())

    def test_combined_pi_axis_has_no_confidence_band_or_gap_interpolation(self):
        forbidden = ("confidence", "conf_int", "ci_lower", "ci_upper", "band")
        for key in recursive_keys(self.metadata):
            normalized = key.casefold()
            self.assertFalse(
                any(token in normalized for token in forbidden),
                f"Confidence-band metadata is not requested: {key}",
            )
        shaded = [
            artist
            for artist in self.axis.collections
            if isinstance(artist, PolyCollection)
        ]
        self.assertEqual(shaded, [])
        self.assertFalse(self.metadata.get("missing_terms_connected", True))


class CombinedPiScaleAndIdentityTests(unittest.TestCase):
    def capture_indicator(self, rows: list[dict[str, object]]):
        captured: dict[str, object] = {}

        def capture_chart(figure, **kwargs):
            captured["figure"] = figure
            captured.update(kwargs)
            return kwargs

        with patch.object(analysis_engine, "_chart", side_effect=capture_chart):
            analysis_engine._indicator_chart(analyze_rows(rows), pyplot)
        self.addCleanup(pyplot.close, captured["figure"])
        return captured, captured["figure"]

    def assert_only_fitted_lines_and_no_band(self, figure, metadata) -> None:
        self.assertEqual(len(figure.axes), 1)
        for line in figure.axes[0].lines:
            label = str(line.get_label()).casefold()
            self.assertIn("fitted trend", label)
            self.assertNotIn("observed", label)
            self.assertNotIn("target", label)
            self.assertNotIn("segment", label)
        self.assertFalse(
            any(
                isinstance(artist, PolyCollection)
                for artist in figure.axes[0].collections
            )
        )
        forbidden = ("confidence", "conf_int", "ci_lower", "ci_upper", "band")
        self.assertFalse(
            any(
                token in key.casefold()
                for key in recursive_keys(metadata)
                for token in forbidden
            )
        )

    def test_thirteen_pis_remain_one_axis_with_all_naturally_ordered_blocks(self):
        rows = [
            assessment_row(
                campus=campus,
                indicator_id=indicator_id,
                indicator_code=f"PI-{indicator_id}",
                term_position=term_position,
                attainment=(
                    52 + indicator_id + 3 * term_position
                    if campus == "Edinburg"
                    else 91 - indicator_id - 3 * term_position
                ),
                target=(
                    65 + term_position
                    if campus == "Edinburg"
                    else 76 - term_position
                ),
                bloom_level=("Understand", "Apply", "Analyze")[term_position],
            )
            for indicator_id in range(13, 0, -1)
            for campus in ("Brownsville", "Edinburg")
            for term_position in (2, 0, 1)
        ]
        captured, figure = self.capture_indicator(rows)
        metadata = captured["metadata"]
        blocks = metadata["pi_blocks"]

        self.assertEqual(captured["chart_type"], "combined_pi_trend")
        self.assertEqual(metadata["layout"], "single_axis_pi_blocks")
        self.assertEqual(metadata["axis_count"], 1)
        self.assertEqual(metadata["panel_count"], 13)
        self.assertEqual(len(blocks), 13)
        self.assertEqual(
            [block["indicator_code"] for block in blocks],
            [f"PI-{indicator_id}" for indicator_id in range(1, 14)],
        )
        self.assertEqual(metadata["x_tick_labels"], TERM_LABELS * 13)
        self.assertNotIn("no more than 12", str(captured["alt_text"]).casefold())
        self.assertGreaterEqual(metadata["display_width_px"], 900)
        self.assertLessEqual(metadata["display_width_px"], 4200)

        palette = metadata["pi_palette"]
        self.assertGreaterEqual(len(palette), 3)
        self.assertGreaterEqual(
            len({mcolors.to_hex(color) for color in palette}),
            3,
        )
        self.assertEqual(
            [block["palette_index"] for block in blocks],
            [index % len(palette) for index in range(13)],
        )
        self.assertEqual(
            [mcolors.to_hex(block["pi_color"]) for block in blocks],
            [mcolors.to_hex(palette[index % len(palette)]) for index in range(13)],
        )

        fit_labels = {
            str(line.get_label()) for line in figure.axes[0].lines
        }
        self.assertEqual(len(fit_labels), 26)
        for indicator_id in range(1, 14):
            for campus in ("Edinburg", "Brownsville"):
                self.assertIn(
                    f"PI-{indicator_id} · {campus} fitted trend",
                    fit_labels,
                )
                line = next(
                    artist
                    for artist in figure.axes[0].lines
                    if str(artist.get_label())
                    == f"PI-{indicator_id} · {campus} fitted trend"
                )
                self.assertEqual(
                    mcolors.to_hex(line.get_color()),
                    mcolors.to_hex(blocks[indicator_id - 1]["pi_color"]),
                )
        target_collections = [
            artist
            for artist in figure.axes[0].collections
            if "target" in str(artist.get_label()).casefold()
        ]
        self.assertTrue(target_collections)
        self.assert_only_fitted_lines_and_no_band(figure, metadata)

    def test_repeated_pi_codes_under_different_outcomes_have_distinct_blocks(self):
        rows: list[dict[str, object]] = []
        for outcome_id, outcome_code, outcome_order in (
            (2, "SLO2", 2),
            (1, "SLO1", 1),
        ):
            for campus in ("Brownsville", "Edinburg"):
                for term_position in (2, 0, 1):
                    row = assessment_row(
                        campus=campus,
                        indicator_id=1,
                        indicator_code="PI-1",
                        term_position=term_position,
                        attainment=(
                            62 + outcome_order * 4 + term_position * 3
                            if campus == "Edinburg"
                            else 86 - outcome_order * 3 - term_position * 2
                        ),
                        target=68 + outcome_order + term_position,
                        bloom_level=("Understand", "Apply", "Analyze")[term_position],
                    )
                    row.update(
                        {
                            "outcome_id": outcome_id,
                            "outcome_code": outcome_code,
                            "outcome_label": f"{outcome_code}: Test outcome",
                            "outcome_order": outcome_order,
                        }
                    )
                    rows.append(row)

        captured, figure = self.capture_indicator(rows)
        metadata = captured["metadata"]
        blocks = metadata["pi_blocks"]
        self.assertEqual(captured["chart_type"], "combined_pi_trend")
        self.assertEqual(len(figure.axes), 1)
        self.assertEqual(
            [block["block_label"] for block in blocks],
            ["SLO1 · PI-1", "SLO2 · PI-1"],
        )
        self.assertEqual(
            [block["indicator_code"] for block in blocks],
            ["PI-1", "PI-1"],
        )
        self.assertEqual(metadata["x_tick_labels"], TERM_LABELS * 2)
        fit_labels = {
            str(line.get_label()) for line in figure.axes[0].lines
        }
        self.assertEqual(
            fit_labels,
            {
                f"{outcome} · PI-1 · {campus} fitted trend"
                for outcome in ("SLO1", "SLO2")
                for campus in ("Edinburg", "Brownsville")
            },
        )
        self.assert_only_fitted_lines_and_no_band(figure, metadata)


if __name__ == "__main__":
    unittest.main()
