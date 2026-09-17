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


TERM_ROWS = (
    (81, "Fall 2021", 10),
    (12, "Spring 2022", 20),
    (75, "Fall 2022", 30),
    (24, "Spring 2023", 40),
    (69, "Fall 2023", 50),
    (36, "Spring 2024", 60),
    (57, "Fall 2024", 70),
    (48, "Spring 2025", 80),
)
TERM_LABELS = [label for _term_id, label, _order in TERM_ROWS]
BLOOM_LEVELS = ("Understand", "Apply", "Analyze", "Evaluate", "Create")


def dense_readability_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for indicator_id in (3, 1, 2):
        for campus in ("Brownsville", "Edinburg"):
            for term_position in (7, 1, 5, 0, 6, 2, 4, 3):
                term_id, term_label, term_order = TERM_ROWS[term_position]
                if campus == "Edinburg":
                    attainment = min(100.0, 57 + 5 * indicator_id + 4 * term_position)
                    target = min(100.0, 66 + indicator_id + 3 * term_position)
                else:
                    attainment = max(45.0, 96 - 4 * indicator_id - 3 * term_position)
                    target = min(100.0, 74 + 2 * indicator_id + 2 * term_position)

                # Explicit ceiling values exercise the exact clipping concern
                # that motivated the requested 110% display bound.
                if indicator_id == 1 and campus == "Edinburg" and term_position == 7:
                    attainment = 100.0
                if indicator_id == 2 and campus == "Brownsville" and term_position == 0:
                    attainment = 100.0
                if indicator_id == 3 and campus == "Brownsville" and term_position == 7:
                    target = 100.0
                if indicator_id == 2 and campus == "Edinburg" and term_position == 7:
                    target = 100.0

                rows.append(
                    {
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
                        "indicator_code": f"PI-{indicator_id}",
                        "indicator_label": f"PI-{indicator_id}: Test indicator",
                        "bloom_level": BLOOM_LEVELS[
                            (indicator_id + term_position) % len(BLOOM_LEVELS)
                        ],
                        "attainment": attainment,
                        "target": target,
                        "status": "approved",
                    }
                )
    return rows


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


class CombinedPiReadabilityTests(unittest.TestCase):
    def setUp(self):
        self.rows = dense_readability_rows()
        self.captured: dict[str, object] = {}

        def capture_chart(figure, **kwargs):
            self.captured["figure"] = figure
            self.captured.update(kwargs)
            return kwargs

        with patch.object(analysis_engine, "_chart", side_effect=capture_chart):
            analysis_engine._indicator_chart(analyze_rows(self.rows), pyplot)
        self.figure = self.captured["figure"]
        self.assertEqual(len(self.figure.axes), 1)
        self.axis = self.figure.axes[0]
        self.metadata = self.captured["metadata"]

    def tearDown(self):
        pyplot.close(self.figure)

    def path_collections(self, token: str) -> list[PathCollection]:
        return [
            artist
            for artist in self.axis.collections
            if isinstance(artist, PathCollection)
            and token in str(artist.get_label()).casefold()
        ]

    def observation_collections(self) -> list[PathCollection]:
        # Campus/Bloom observations deliberately suppress per-point legend
        # entries; the two figure legends explain campus color and Bloom shape.
        return [
            artist
            for artist in self.axis.collections
            if isinstance(artist, PathCollection)
            and "target" not in str(artist.get_label()).casefold()
        ]

    @staticmethod
    def contrast_against_white(color: object) -> float:
        red, green, blue, _alpha = mcolors.to_rgba(color)

        def linearize(channel: float) -> float:
            if channel <= 0.04045:
                return channel / 12.92
            return ((channel + 0.055) / 1.055) ** 2.4

        luminance = (
            0.2126 * linearize(red)
            + 0.7152 * linearize(green)
            + 0.0722 * linearize(blue)
        )
        return 1.05 / (luminance + 0.05)

    @staticmethod
    def assert_rgba_equal(actual: object, expected: object) -> None:
        np.testing.assert_allclose(
            np.asarray(mcolors.to_rgba(actual), dtype=float)[:3],
            np.asarray(mcolors.to_rgba(expected), dtype=float)[:3],
            atol=1e-7,
        )

    def observation_collections_for(
        self, block: dict[str, object], campus: str
    ) -> list[PathCollection]:
        offset = float(self.metadata["campus_x_offsets"][campus])
        expected_x = np.asarray(block["x_positions"], dtype=float) + offset
        matches: list[PathCollection] = []
        for artist in self.observation_collections():
            points = np.asarray(artist.get_offsets(), dtype=float)
            if not len(points):
                continue
            if all(
                bool(np.any(np.isclose(expected_x, float(x_value))))
                for x_value in points[:, 0]
            ):
                matches.append(artist)
        return matches

    def test_y_axis_uses_110_and_keeps_100_percent_symbols_inside(self):
        lower, upper = self.axis.get_ylim()
        self.assertLess(lower, 100.0)
        self.assertEqual(upper, 110.0)

        observed = self.observation_collections()
        targets = self.path_collections("target")
        self.assertTrue(observed)
        self.assertTrue(targets)
        observed_y = [
            float(y)
            for artist in observed
            for _x, y in np.asarray(artist.get_offsets(), dtype=float)
        ]
        target_y = [
            float(y)
            for artist in targets
            for _x, y in np.asarray(artist.get_offsets(), dtype=float)
        ]
        self.assertIn(100.0, observed_y)
        self.assertIn(100.0, target_y)
        for value in [item for item in observed_y + target_y if item == 100.0]:
            self.assertGreaterEqual(
                upper - value,
                10.0,
                "A 100% marker needs visible headroom rather than being clipped at the frame.",
            )

    def test_markers_lines_and_typography_are_meaningfully_larger(self):
        observed = self.observation_collections()
        targets = self.path_collections("target")
        self.assertTrue(observed)
        self.assertTrue(targets)
        self.assertTrue(
            all(float(np.min(artist.get_sizes())) >= 80.0 for artist in observed)
        )
        self.assertTrue(
            all(float(np.min(artist.get_sizes())) >= 110.0 for artist in targets)
        )
        self.assertTrue(self.axis.lines)
        self.assertTrue(
            all(float(line.get_linewidth()) >= 2.7 for line in self.axis.lines)
        )

        self.assertGreaterEqual(self.axis.xaxis.label.get_fontsize(), 11.0)
        self.assertGreaterEqual(self.axis.yaxis.label.get_fontsize(), 11.0)
        self.assertTrue(
            all(label.get_fontsize() >= 9.0 for label in self.axis.get_xticklabels())
        )
        self.assertTrue(
            all(label.get_fontsize() >= 9.0 for label in self.axis.get_yticklabels())
        )
        pi_headers = [
            item
            for item in self.axis.texts
            if item.get_text() in {"PI-1", "PI-2", "PI-3"}
        ]
        self.assertEqual(len(pi_headers), 3)
        self.assertTrue(all(item.get_fontsize() >= 12.0 for item in pi_headers))
        self.assertIsNotNone(self.figure._suptitle)
        self.assertGreaterEqual(self.figure._suptitle.get_fontsize(), 16.0)
        self.assertTrue(self.figure.legends)
        for legend in self.figure.legends:
            self.assertGreaterEqual(legend.get_title().get_fontsize(), 9.0)
            self.assertTrue(
                all(item.get_fontsize() >= 9.0 for item in legend.get_texts())
            )

    def test_dense_chart_retains_single_axis_scatter_only_and_no_confidence_band(self):
        self.assertEqual(self.captured["chart_type"], "combined_pi_trend")
        self.assertEqual(self.metadata["layout"], "single_axis_pi_blocks")
        self.assertEqual(self.metadata["axis_count"], 1)
        self.assertEqual(
            [block["indicator_code"] for block in self.metadata["pi_blocks"]],
            ["PI-1", "PI-2", "PI-3"],
        )
        self.assertEqual(self.metadata["x_tick_labels"], TERM_LABELS * 3)
        self.assertEqual(len(self.axis.get_xticklabels()), len(TERM_ROWS) * 3)

        self.assertTrue(self.axis.lines)
        for line in self.axis.lines:
            label = str(line.get_label()).casefold()
            self.assertIn("fitted trend", label)
            self.assertNotIn("observed", label)
            self.assertNotIn("target", label)
            self.assertNotIn("segment", label)
        self.assertFalse(
            any(
                isinstance(artist, PolyCollection)
                for artist in self.axis.collections
            )
        )

    def test_pi_colors_and_redundant_campus_encodings_are_explicit_and_rendered(self):
        blocks = self.metadata["pi_blocks"]
        palette = self.metadata["pi_palette"]
        encodings = self.metadata["campus_encodings"]

        self.assertGreaterEqual(len(palette), 3)
        first_three = [mcolors.to_hex(color) for color in palette[:3]]
        self.assertEqual(len(set(first_three)), 3)
        self.assertTrue(
            all(self.contrast_against_white(color) >= 3.0 for color in palette),
            "Every cycled PI color labels large bold headings and must remain legible on white.",
        )

        self.assertEqual(set(encodings), {"Edinburg", "Brownsville"})
        self.assertNotEqual(
            encodings["Edinburg"]["line_style"],
            encodings["Brownsville"]["line_style"],
        )
        self.assertNotEqual(
            encodings["Edinburg"]["observation_fill"],
            encodings["Brownsville"]["observation_fill"],
        )
        self.assertNotEqual(
            encodings["Edinburg"]["x_offset"],
            encodings["Brownsville"]["x_offset"],
        )

        heading_by_label = {text.get_text(): text for text in self.axis.texts}
        for block in blocks:
            pi_color = block["pi_color"]
            palette_index = block["palette_index"]
            self.assertEqual(
                mcolors.to_hex(pi_color),
                mcolors.to_hex(palette[palette_index]),
            )
            self.assert_rgba_equal(
                heading_by_label[block["block_label"]].get_color(), pi_color
            )

            for campus in ("Edinburg", "Brownsville"):
                observations = self.observation_collections_for(block, campus)
                self.assertTrue(
                    observations,
                    f"{block['block_label']} · {campus} observations are missing.",
                )
                for artist in observations:
                    facecolors = artist.get_facecolors()
                    edgecolors = artist.get_edgecolors()
                    if campus == "Edinburg":
                        self.assertTrue(len(facecolors))
                        self.assertGreater(float(facecolors[0, 3]), 0.5)
                        self.assert_rgba_equal(facecolors[0], pi_color)
                    else:
                        self.assertTrue(
                            not len(facecolors)
                            or all(
                                float(color[3]) == 0.0
                                or np.allclose(color[:3], mcolors.to_rgb("white"))
                                for color in facecolors
                            ),
                            "Brownsville must remain white-filled and outlined, not solid like Edinburg.",
                        )
                        self.assertTrue(len(edgecolors))
                        self.assert_rgba_equal(edgecolors[0], pi_color)

                fit_label = f"{block['block_label']} · {campus} fitted trend"
                fit = next(
                    line
                    for line in self.axis.lines
                    if str(line.get_label()) == fit_label
                )
                self.assert_rgba_equal(fit.get_color(), pi_color)
                self.assertEqual(
                    fit.get_linestyle(), encodings[campus]["line_style_code"]
                )

                target_label = (
                    f"{block['block_label']} · {campus} configured target"
                )
                target = next(
                    artist
                    for artist in self.axis.collections
                    if str(artist.get_label()) == target_label
                )
                target_colors = target.get_edgecolors()
                self.assertTrue(len(target_colors))
                self.assert_rgba_equal(target_colors[0], pi_color)
                self.assertAlmostEqual(
                    float(target.get_alpha()),
                    float(encodings[campus]["target_alpha"]),
                )

        self.assertNotEqual(
            next(
                line
                for line in self.axis.lines
                if "Edinburg fitted trend" in str(line.get_label())
            ).get_linestyle(),
            next(
                line
                for line in self.axis.lines
                if "Brownsville fitted trend" in str(line.get_label())
            ).get_linestyle(),
        )

    def test_legends_explain_campus_encoding_and_every_bloom_shape(self):
        legends = {
            legend.get_title().get_text(): legend for legend in self.figure.legends
        }
        self.assertIn(self.metadata["legend_title"], legends)
        self.assertIn(self.metadata["bloom_legend_title"], legends)

        campus_labels = {
            item.get_text()
            for item in legends[self.metadata["legend_title"]].get_texts()
        }
        expected_semantics = {
            "Edinburg": ("filled", "solid", "left"),
            "Brownsville": ("hollow", "dash-dot", "right"),
        }
        for campus, semantics in expected_semantics.items():
            label = next(
                item for item in campus_labels if item.startswith(campus)
            )
            self.assertTrue(
                all(token in label.casefold() for token in semantics),
                f"Campus legend does not explain {campus}'s redundant encoding.",
            )
        target_label = next(
            item for item in campus_labels if "target" in item.casefold()
        )
        self.assertIn("underscore", target_label.casefold())

        bloom_labels = [
            item.get_text()
            for item in legends[self.metadata["bloom_legend_title"]].get_texts()
        ]
        self.assertEqual(bloom_labels, self.metadata["bloom_levels"])
        bloom_legend = legends[self.metadata["bloom_legend_title"]]
        handles = getattr(
            bloom_legend,
            "legend_handles",
            getattr(bloom_legend, "legendHandles", []),
        )
        self.assertEqual(len(handles), len(bloom_labels))
        rendered_markers = [handle.get_marker() for handle in handles]
        expected_markers = [
            self.metadata["bloom_markers"][level] for level in bloom_labels
        ]
        self.assertEqual(rendered_markers, expected_markers)
        forbidden = ("confidence", "conf_int", "ci_lower", "ci_upper", "band")
        self.assertFalse(
            any(
                token in key.casefold()
                for key in recursive_keys(self.metadata)
                for token in forbidden
            )
        )


if __name__ == "__main__":
    unittest.main()
