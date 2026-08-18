"""Statistical summaries and accessible chart assets for assessment evidence.

Each assessment record is treated as one observation.  This is intentional:
legacy UTRGV rows contain percentages but no trustworthy student denominator, so
weighting modern rows by sample size would make the combined analysis misleading.
"""

from __future__ import annotations

import base64
import io
import math
import re
from collections import Counter, defaultdict
from statistics import median, stdev
from typing import Any, Iterable

import numpy as np
from scipy import stats


BLOOM_ORDER = ("Remember", "Understand", "Apply", "Analyze", "Evaluate", "Create")
_BLOOM_RANK = {level: index for index, level in enumerate(BLOOM_ORDER)}
_COLORS = ("#003638", "#ee7f2f", "#00736f", "#7c4d8f", "#b94747", "#3f6f9f")
CAMPUS_ORDER = ("Edinburg", "Brownsville")


def _as_dict(row: Any) -> dict[str, Any]:
    return dict(row)


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _bloom_level(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "Unspecified"
    for level in BLOOM_ORDER:
        if text.casefold() == level.casefold():
            return level
    return text


def _display_indicator_code(value: Any) -> str:
    code = str(value or "Indicator").strip()
    if code.upper().startswith("UNMAPPED"):
        return "Unmapped source PI"
    if code.upper().endswith("-H"):
        return f"{code[:-2]} (source alias)"
    return code


def _normalized_rows(
    rows: Iterable[Any],
    *,
    selected_courses: Iterable[Any] | None,
    approved_only: bool,
    statuses: Iterable[str] | None,
) -> list[dict[str, Any]]:
    allowed_statuses = {str(status) for status in statuses} if statuses is not None else None
    course_tokens = set(selected_courses or ())
    normalized = []
    for source in rows:
        row = _as_dict(source)
        if approved_only and row.get("status") != "approved":
            continue
        if allowed_statuses is not None and row.get("status") not in allowed_statuses:
            continue
        if course_tokens and not {
            row.get("course_id"),
            row.get("course_code"),
            row.get("course_label"),
        }.intersection(course_tokens):
            continue
        attainment = _number(row.get("attainment"))
        target = _number(row.get("target"))
        if attainment is None or target is None:
            continue
        row["attainment"] = attainment
        row["target"] = target
        row["bloom_level"] = _bloom_level(row.get("bloom_level"))
        raw_campus = str(row.get("campus") or "Unassigned").strip()
        row["campus"] = next(
            (
                campus
                for campus in CAMPUS_ORDER
                if raw_campus.casefold() == campus.casefold()
            ),
            "Unassigned",
        )
        normalized.append(row)
    return normalized


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _summary(
    dimension: str,
    key: Any,
    label: str,
    items: list[dict[str, Any]],
    **extra: Any,
) -> dict[str, Any]:
    values = [float(item["attainment"]) for item in items]
    targets = [float(item["target"]) for item in items]
    mean_value = _mean(values)
    mean_target = _mean(targets)
    target_gap = _mean(
        [value - target for value, target in zip(values, targets, strict=True)]
    )
    met_count = sum(value >= target for value, target in zip(values, targets))
    status_counts = Counter(str(item.get("status") or "unknown") for item in items)
    return {
        "dimension": dimension,
        "key": key,
        "label": label,
        "count": len(items),
        "mean": mean_value,
        "average": round(mean_value, 1),
        "median": round(float(median(values)), 2),
        "minimum": round(min(values), 2),
        "maximum": round(max(values), 2),
        "standard_deviation": round(float(stdev(values)), 2) if len(values) > 1 else 0.0,
        "target": round(mean_target, 2),
        "target_gap": target_gap,
        "met_count": met_count,
        "met_rate": round(100.0 * met_count / len(items), 1),
        "meets_target": mean_value >= mean_target,
        "status_counts": dict(status_counts),
        **extra,
    }


def _group_summaries(
    rows: list[dict[str, Any]],
    *,
    dimension: str,
    key_fields: tuple[str, ...],
    label,
    sort_key,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[tuple(row.get(field) for field in key_fields)].append(row)
    summaries = []
    for key, items in grouped.items():
        entity_key: Any = key[0] if len(key) == 1 else key
        summaries.append(_summary(dimension, entity_key, label(items[0]), items))
    return sorted(summaries, key=sort_key)


def _bloom_summaries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["bloom_level"]].append(row)
    result = [
        _summary("bloom", level, level, items, level=level)
        for level, items in grouped.items()
    ]
    return sorted(
        result,
        key=lambda item: (_BLOOM_RANK.get(item["level"], len(BLOOM_ORDER)), item["level"]),
    )


def _campus_summaries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["campus"]].append(row)
    result = [
        _summary("campus", campus, campus, items, campus=campus)
        for campus, items in grouped.items()
    ]
    order = {campus: index for index, campus in enumerate(CAMPUS_ORDER)}
    return sorted(result, key=lambda item: (order.get(item["label"], 99), item["label"]))


def _campus_group_rows(
    rows: list[dict[str, Any]], dimension: str
) -> list[dict[str, Any]]:
    specs = {
        "term": (
            ("term_id",),
            lambda row: str(row.get("term_label") or "Term"),
            lambda row: (_number(row.get("term_order")) or 0, str(row.get("term_label") or "")),
        ),
        "course": (
            ("course_id",),
            lambda row: str(row.get("course_label") or row.get("course_code") or "Course"),
            lambda row: (str(row.get("course_code") or row.get("course_label") or ""),),
        ),
        "outcome": (
            ("outcome_id",),
            lambda row: str(row.get("outcome_label") or row.get("outcome_code") or "Outcome"),
            lambda row: (_number(row.get("outcome_order")) or 0, str(row.get("outcome_code") or "")),
        ),
        "indicator": (
            ("outcome_id", "indicator_id"),
            lambda row: (
                f"{row.get('outcome_code') or 'Outcome'} · "
                f"{_display_indicator_code(row.get('indicator_code') or row.get('indicator_label'))}"
            ),
            lambda row: (
                _number(row.get("outcome_order")) or 0,
                str(row.get("indicator_code") or row.get("indicator_label") or ""),
            ),
        ),
    }
    key_fields, label_for, sort_for = specs[dimension]
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["campus"] in CAMPUS_ORDER:
            grouped[tuple(row.get(field) for field in key_fields)].append(row)
    result = []
    for key, items in grouped.items():
        campus_values = {}
        for campus in CAMPUS_ORDER:
            evidence = [item for item in items if item["campus"] == campus]
            if not evidence:
                campus_values[campus] = None
                continue
            attainments = [float(item["attainment"]) for item in evidence]
            targets = [float(item["target"]) for item in evidence]
            campus_values[campus] = {
                "count": len(evidence),
                "mean": _mean(attainments),
                "target": _mean(targets),
                "target_gap": _mean(
                    [
                        attainment - target
                        for attainment, target in zip(attainments, targets, strict=True)
                    ]
                ),
                "met_count": sum(
                    attainment >= target
                    for attainment, target in zip(attainments, targets, strict=True)
                ),
            }
        edinburg = campus_values["Edinburg"]
        brownsville = campus_values["Brownsville"]
        result.append(
            {
                "key": key[0] if len(key) == 1 else key,
                "label": label_for(items[0]),
                "sort_key": sort_for(items[0]),
                "campuses": campus_values,
                "comparable": edinburg is not None and brownsville is not None,
                "attainment_difference": (
                    brownsville["mean"] - edinburg["mean"]
                    if edinburg is not None and brownsville is not None
                    else None
                ),
                "target_gap_difference": (
                    brownsville["target_gap"] - edinburg["target_gap"]
                    if edinburg is not None and brownsville is not None
                    else None
                ),
            }
        )
    result.sort(key=lambda item: item["sort_key"])
    for item in result:
        item.pop("sort_key", None)
    return result


def _campus_comparison(
    rows: list[dict[str, Any]],
    summaries: list[dict[str, Any]],
    group_dimension: str,
) -> dict[str, Any]:
    summary_by_campus = {item["label"]: item for item in summaries}
    groups = _campus_group_rows(rows, group_dimension)
    base = {
        "status": "unavailable",
        "reason": None,
        "difference_direction": "Brownsville minus Edinburg",
        "attainment_difference": None,
        "target_gap_difference": None,
        "met_rate_difference": None,
        "higher_attainment_campus": None,
        "stronger_target_adjusted_campus": None,
        "group_dimension": group_dimension,
        "groups": groups,
        "comparable_group_count": sum(item["comparable"] for item in groups),
        "group_count": len(groups),
    }
    edinburg = summary_by_campus.get("Edinburg")
    brownsville = summary_by_campus.get("Brownsville")
    if not edinburg or not brownsville:
        missing = [campus for campus in CAMPUS_ORDER if campus not in summary_by_campus]
        base["reason"] = (
            "Campus comparison requires at least one usable assessment measure from "
            "both Edinburg and Brownsville. Missing: " + ", ".join(missing) + "."
        )
        return base
    attainment_difference = brownsville["mean"] - edinburg["mean"]
    target_gap_difference = brownsville["target_gap"] - edinburg["target_gap"]
    met_rate_difference = brownsville["met_rate"] - edinburg["met_rate"]

    def direction(value: float, positive: str, negative: str) -> str:
        if value > 1e-12:
            return positive
        if value < -1e-12:
            return negative
        return "Tie"

    return {
        **base,
        "status": "available",
        "attainment_difference": attainment_difference,
        "target_gap_difference": target_gap_difference,
        "met_rate_difference": met_rate_difference,
        "higher_attainment_campus": direction(
            attainment_difference, "Brownsville", "Edinburg"
        ),
        "stronger_target_adjusted_campus": direction(
            target_gap_difference, "Brownsville", "Edinburg"
        ),
    }


def _indicator_summaries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, Any], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row.get("outcome_id"), row.get("indicator_id"))].append(row)
    result = []
    for key, items in grouped.items():
        first = items[0]
        outcome_code = str(first.get("outcome_code") or "Outcome")
        indicator_code = _display_indicator_code(
            first.get("indicator_code") or first.get("indicator_label")
        )
        result.append(
            _summary(
                "indicator",
                key,
                f"{outcome_code} · {indicator_code}",
                items,
                outcome_id=key[0],
                indicator_id=key[1],
                outcome_code=outcome_code,
                indicator_code=indicator_code,
            )
        )
    return sorted(
        result,
        key=lambda item: (
            min(
                (
                    row.get("outcome_order", 0),
                    row.get("indicator_code", ""),
                )
                for row in rows
                if row.get("outcome_id") == item["outcome_id"]
                and row.get("indicator_id") == item["indicator_id"]
            ),
            item["label"],
        ),
    )


def _indicator_bloom_summaries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, Any, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[
            (row.get("outcome_id"), row.get("indicator_id"), row["bloom_level"])
        ].append(row)
    result = []
    for key, items in grouped.items():
        first = items[0]
        outcome_code = str(first.get("outcome_code") or "Outcome")
        indicator_code = _display_indicator_code(
            first.get("indicator_code") or first.get("indicator_label")
        )
        result.append(
            _summary(
                "indicator_bloom",
                key,
                f"{outcome_code} · {indicator_code} ({key[2]})",
                items,
                outcome_id=key[0],
                indicator_id=key[1],
                level=key[2],
            )
        )
    return sorted(
        result,
        key=lambda item: (
            item["label"].rsplit(" (", 1)[0],
            _BLOOM_RANK.get(item["level"], len(BLOOM_ORDER)),
            item["level"],
        ),
    )


def _kruskal_wallis(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        if row["bloom_level"] != "Unspecified":
            grouped[row["bloom_level"]].append(float(row["attainment"]))
    ordered = [
        (level, grouped[level])
        for level in sorted(
            grouped,
            key=lambda value: (_BLOOM_RANK.get(value, len(BLOOM_ORDER)), value),
        )
        if grouped[level]
    ]
    base = {
        "status": "unavailable",
        "h_statistic": None,
        "p_value": None,
        "group_count": len(ordered),
        "levels": [level for level, _ in ordered],
        "significant": None,
        "reason": None,
    }
    if len(ordered) < 2:
        base["reason"] = "At least two populated Bloom levels are required."
        return base
    all_values = [value for _, values in ordered for value in values]
    if len(set(all_values)) < 2:
        base["reason"] = "All Bloom-level attainment values are identical."
        return base
    try:
        result = stats.kruskal(*(values for _, values in ordered), nan_policy="omit")
    except ValueError as error:
        base["reason"] = f"The test could not be computed: {error}"
        return base
    statistic = float(result.statistic)
    p_value = float(result.pvalue)
    if not math.isfinite(statistic) or not math.isfinite(p_value):
        base["reason"] = "The available Bloom data did not produce a finite test result."
        return base
    return {
        **base,
        "status": "available",
        "h_statistic": statistic,
        "p_value": p_value,
        "significant": p_value < 0.05,
        "reason": None,
    }


def _cliffs_delta(rows: list[dict[str, Any]]) -> dict[str, Any]:
    analyze = [
        float(row["attainment"]) for row in rows if row["bloom_level"] == "Analyze"
    ]
    others = [
        float(row["attainment"])
        for row in rows
        if row["bloom_level"] not in {"Analyze", "Unspecified"}
    ]
    base = {
        "status": "unavailable",
        "delta": None,
        "magnitude": None,
        "analyze_count": len(analyze),
        "other_count": len(others),
        "reason": None,
    }
    if not analyze or not others:
        base["reason"] = "Analyze-level evidence and at least one other Bloom level are required."
        return base
    left = np.asarray(analyze, dtype=float)[:, None]
    right = np.asarray(others, dtype=float)[None, :]
    delta = float((np.sum(left > right) - np.sum(left < right)) / left.size / right.size)
    absolute = abs(delta)
    if absolute < 0.147:
        magnitude = "negligible"
    elif absolute < 0.33:
        magnitude = "small"
    elif absolute < 0.474:
        magnitude = "medium"
    else:
        magnitude = "large"
    return {
        **base,
        "status": "available",
        "delta": delta,
        "magnitude": magnitude,
        "reason": None,
    }


def _trend(rows: list[dict[str, Any]], terms: list[dict[str, Any]]) -> dict[str, Any]:
    trend_terms = [
        {
            "key": item["key"],
            "label": item["label"],
            "count": item["count"],
            "mean": item["mean"],
            "average": item["average"],
            "term_order": item.get("term_order"),
            "fitted": None,
        }
        for item in terms
    ]
    base = {
        "status": "unavailable",
        "n": len(rows),
        "term_count": len(terms),
        "slope": None,
        "intercept": None,
        "r_squared": None,
        "p_value": None,
        "standard_error": None,
        "confidence_interval_95": None,
        "direction": None,
        "terms": trend_terms,
        "reason": None,
    }
    if len(terms) < 2:
        base["reason"] = "At least two academic terms are required for a trend."
        return base
    raw_x = [item.get("term_order") for item in terms]
    if all(_number(value) is not None for value in raw_x) and len(set(raw_x)) == len(raw_x):
        x = np.asarray([float(value) for value in raw_x], dtype=float)
    else:
        x = np.arange(len(terms), dtype=float)
    y = np.asarray([float(item["mean"]) for item in terms], dtype=float)
    result = stats.linregress(x, y)
    slope = float(result.slope)
    standard_error = float(result.stderr) if result.stderr is not None else None
    if not math.isfinite(slope):
        base["reason"] = "The term means did not produce a finite trend."
        return base
    if abs(slope) < 1e-12:
        direction = "stable"
    else:
        direction = "increasing" if slope > 0 else "decreasing"
    interval = None
    if standard_error is not None and math.isfinite(standard_error):
        interval = [slope - 1.96 * standard_error, slope + 1.96 * standard_error]
    for item, x_value in zip(trend_terms, x):
        item["fitted"] = round(float(result.intercept + slope * x_value), 2)
    return {
        **base,
        "status": "available",
        "slope": slope,
        "intercept": float(result.intercept),
        "r_squared": float(result.rvalue**2),
        "p_value": float(result.pvalue),
        "standard_error": standard_error,
        "confidence_interval_95": interval,
        "direction": direction,
        "reason": None,
    }


def analyze_rows(
    rows: Iterable[Any],
    selected_courses: Iterable[Any] | None = None,
    approved_only: bool = False,
    statuses: Iterable[str] | None = None,
    campus_group: str = "term",
) -> dict[str, Any]:
    """Return analysis-ready summaries without mutating or weighting source rows."""
    data = _normalized_rows(
        rows,
        selected_courses=selected_courses,
        approved_only=approved_only,
        statuses=statuses,
    )
    if campus_group not in {"term", "course", "outcome", "indicator"}:
        raise ValueError("Unknown campus comparison grouping.")
    courses = _group_summaries(
        data,
        dimension="course",
        key_fields=("course_id",),
        label=lambda row: str(row.get("course_label") or row.get("course_code") or "Course"),
        sort_key=lambda item: item["label"],
    )
    terms = _group_summaries(
        data,
        dimension="term",
        key_fields=("term_id",),
        label=lambda row: str(row.get("term_label") or "Term"),
        sort_key=lambda item: (
            _number(
                next(
                    (
                        row.get("term_order")
                        for row in data
                        if row.get("term_id") == item["key"]
                    ),
                    0,
                )
            )
            or 0,
            item["label"],
        ),
    )
    for item in terms:
        item["term_order"] = next(
            (row.get("term_order") for row in data if row.get("term_id") == item["key"]),
            0,
        )
    outcomes = _group_summaries(
        data,
        dimension="outcome",
        key_fields=("outcome_id",),
        label=lambda row: str(row.get("outcome_label") or row.get("outcome_code") or "Outcome"),
        sort_key=lambda item: (
            _number(
                next(
                    (
                        row.get("outcome_order")
                        for row in data
                        if row.get("outcome_id") == item["key"]
                    ),
                    0,
                )
            )
            or 0,
            item["label"],
        ),
    )
    bloom = _bloom_summaries(data)
    campuses = _campus_summaries(data)
    indicators = _indicator_summaries(data)
    indicator_bloom = _indicator_bloom_summaries(data)
    selected = sorted(
        {row.get("course_id") for row in data if row.get("course_id") is not None}
    )
    return {
        "rows": data,
        "row_count": len(data),
        "selected_courses": selected,
        "courses": courses,
        "terms": terms,
        "outcomes": outcomes,
        "indicators": indicators,
        "indicator_bloom": indicator_bloom,
        "bloom": bloom,
        "campuses": campuses,
        "campus_comparison": _campus_comparison(data, campuses, campus_group),
        "kruskal_wallis": _kruskal_wallis(data),
        "cliffs_delta": _cliffs_delta(data),
        "trend": _trend(data, terms),
        "methodology": {
            "unit": "assessment measure",
            "weighting": "unweighted",
            "target_basis": "each measure's configured target",
            "campus_comparison": (
                "unweighted assessment measures using each measure's configured target"
            ),
        },
    }


def _unavailable(title: str, reason: str) -> dict[str, Any]:
    return {
        "available": False,
        "title": title,
        "chart_type": None,
        "insights": [],
        "metadata": None,
        "png_base64": None,
        "data_uri": None,
        "alt_text": reason,
        "reason": reason,
    }


def _chart(
    figure,
    *,
    title: str,
    alt_text: str,
    pyplot,
    chart_type: str | None = None,
    insights: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    layout_rect: tuple[float, float, float, float] | None = None,
) -> dict[str, Any]:
    buffer = io.BytesIO()
    try:
        figure.tight_layout(rect=layout_rect)
        figure.savefig(buffer, format="png", dpi=125, bbox_inches="tight", facecolor="white")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    finally:
        pyplot.close(figure)
        buffer.close()
    return {
        "available": True,
        "title": title,
        "chart_type": chart_type,
        "insights": insights or [],
        "metadata": metadata,
        "png_base64": encoded,
        "data_uri": f"data:image/png;base64,{encoded}",
        "alt_text": alt_text,
        "reason": None,
    }


def _course_chart(analysis: dict[str, Any], pyplot) -> dict[str, Any]:
    title = "Attainment by selected course"
    summaries = analysis["courses"]
    if not summaries:
        return _unavailable(title, "No assessment measures are available for the selected courses.")
    height = min(11.0, max(3.2, 0.46 * len(summaries) + 1.7))
    figure, axis = pyplot.subplots(figsize=(8.8, height))
    y = np.arange(len(summaries))
    values = [item["mean"] for item in summaries]
    targets = [item["target"] for item in summaries]
    colors = ["#16867a" if item["meets_target"] else "#b94747" for item in summaries]
    axis.barh(y, values, color=colors, alpha=0.9)
    axis.scatter(targets, y, color="#15212b", marker="|", s=180, linewidths=2.2, label="Mean target")
    axis.set_yticks(y, [item["label"].split(" — ", 1)[0] for item in summaries])
    axis.invert_yaxis()
    axis.set_xlim(0, max(100.0, max(values + targets) + 5))
    axis.set_xlabel("Attainment (%)")
    axis.set_title(title, loc="left", weight="bold")
    axis.grid(axis="x", alpha=0.2)
    axis.legend(loc="lower right", frameon=False)
    for index, value in enumerate(values):
        axis.text(min(value + 1, axis.get_xlim()[1] - 7), index, f"{value:.1f}%", va="center", fontsize=8)
    alt = "; ".join(
        f"{item['label'].split(' — ', 1)[0]} {item['mean']:.1f}% from {item['count']} measures"
        for item in summaries
    )
    return _chart(figure, title=title, alt_text=alt, pyplot=pyplot)


def _format_cell_number(value: float) -> str:
    return f"{value:.0f}" if math.isclose(value, round(value), abs_tol=0.05) else f"{value:.1f}"


def _matrix_insights(
    analysis: dict[str, Any],
    cells: list[dict[str, Any]],
    *,
    possible_cells: int,
    cell_label: str,
) -> list[str]:
    if not cells:
        return []
    met_count = sum(cell["gap"] >= 0 for cell in cells)
    missing_count = possible_cells - len(cells)
    insights = []
    if any(row.get("status") != "approved" for row in analysis["rows"]):
        insights.append("Exploratory preview: this chart includes evidence that is not yet approved.")
    insights.append(
        f"{met_count} of {len(cells)} observed {cell_label} met their configured target."
    )
    weakest = min(cells, key=lambda cell: cell["gap"])
    if weakest["gap"] < 0:
        insights.append(
            f"Largest shortfall: {weakest['row_label']} · {weakest['term_label']} was "
            f"{abs(weakest['gap']):.1f} points below target "
            f"({weakest['attainment']:.1f}% vs target {weakest['target']:.1f}%)."
        )
    else:
        insights.append("No observed cell fell below its configured target.")
    insights.append(
        f"Coverage: {len(cells)} of {possible_cells} possible cells contain evidence; "
        f"{missing_count} are missing."
    )
    latest_index = max(cell["term_index"] for cell in cells)
    latest = [cell for cell in cells if cell["term_index"] == latest_index]
    latest_met = sum(cell["gap"] >= 0 for cell in latest)
    insights.append(
        f"Latest observed term, {latest[0]['term_label']}: {latest_met} of {len(latest)} "
        f"observed cells met target."
    )
    return insights


def _target_gap_heatmap(
    analysis: dict[str, Any],
    pyplot,
    *,
    title: str,
    row_labels: list[str],
    term_labels: list[str],
    attainments: np.ndarray,
    gaps: np.ndarray,
    counts: np.ndarray,
    insights: list[str],
) -> dict[str, Any]:
    from matplotlib.colors import LinearSegmentedColormap

    finite_gaps = gaps[np.isfinite(gaps)]
    maximum_gap = float(np.max(np.abs(finite_gaps))) if finite_gaps.size else 10.0
    span = min(50.0, max(10.0, math.ceil(maximum_gap / 5.0) * 5.0))
    display_gaps = np.clip(gaps, -span, span)
    colors = LinearSegmentedColormap.from_list(
        "target_gap",
        ("#a94f43", "#fff4d6", "#00736f"),
    ).with_extremes(bad="#edf1f3")
    row_count, term_count = gaps.shape
    figure, axis = pyplot.subplots(
        figsize=(
            max(8.2, 0.72 * term_count + 3.2),
            min(24.0, max(3.7, 0.55 * row_count + 2.2)),
        )
    )
    image = axis.imshow(
        np.ma.masked_invalid(display_gaps),
        vmin=-span,
        vmax=span,
        cmap=colors,
        aspect="auto",
    )
    axis.set_xticks(np.arange(term_count), term_labels, rotation=35, ha="right")
    axis.set_yticks(np.arange(row_count), row_labels)
    axis.tick_params(axis="y", labelsize=7 if row_count > 24 else 8.5)
    axis.tick_params(axis="x", labelsize=8)
    axis.set_xlabel("Academic term")
    preview_note = (
        "Exploratory preview • "
        if any(row.get("status") != "approved" for row in analysis["rows"])
        else ""
    )
    axis.set_title(
        f"{title}\n{preview_note}Top: mean attainment %  |  Bottom: points above (+) or below (−) target",
        loc="left",
        weight="bold",
        fontsize=11.5,
        pad=10,
    )
    annotation_size = 5.8 if term_count > 11 or row_count > 20 else 7.2
    for row_index in range(row_count):
        for term_index in range(term_count):
            if not math.isfinite(float(attainments[row_index, term_index])):
                axis.text(
                    term_index,
                    row_index,
                    "—",
                    ha="center",
                    va="center",
                    color="#8b979e",
                    fontsize=annotation_size,
                )
                continue
            attainment = float(attainments[row_index, term_index])
            gap = float(gaps[row_index, term_index])
            count = int(counts[row_index, term_index])
            text_color = "white" if abs(gap) >= span * 0.55 else "#15212b"
            axis.text(
                term_index,
                row_index,
                f"{_format_cell_number(attainment)}%\n{gap:+.1f} · n{count}",
                ha="center",
                va="center",
                color=text_color,
                fontsize=annotation_size,
                fontweight=600,
                linespacing=1.15,
            )
    axis.set_xticks(np.arange(-0.5, term_count, 1), minor=True)
    axis.set_yticks(np.arange(-0.5, row_count, 1), minor=True)
    axis.grid(which="minor", color="white", linewidth=1.5)
    axis.tick_params(which="minor", bottom=False, left=False)
    for spine in axis.spines.values():
        spine.set_visible(False)
    colorbar = figure.colorbar(image, ax=axis, shrink=0.82, pad=0.025)
    colorbar.set_label("Percentage points above (+) or below (−) target", fontsize=8)
    colorbar.ax.tick_params(labelsize=7)
    alt_text = (
        f"Target-gap heatmap with {row_count} rows and {term_count} academic terms. "
        + " ".join(insights)
    )
    return _chart(
        figure,
        title=title,
        alt_text=alt_text,
        pyplot=pyplot,
        chart_type="target_gap_heatmap",
        insights=insights,
    )


def _semester_course_chart(analysis: dict[str, Any], pyplot) -> dict[str, Any]:
    title = "Course performance against target, by term"
    rows = analysis["rows"]
    terms = analysis["terms"]
    courses = analysis["courses"]
    if not rows or not terms or not courses:
        return _unavailable(title, "No term-and-course evidence is available in this selection.")
    grouped: dict[tuple[Any, Any], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row.get("term_id"), row.get("course_id"))].append(row)
    attainments = np.full((len(courses), len(terms)), np.nan)
    gaps = np.full_like(attainments, np.nan)
    counts = np.zeros_like(attainments, dtype=int)
    cells = []
    for course_index, course in enumerate(courses):
        course_label = course["label"].split(" — ", 1)[0]
        for term_index, term in enumerate(terms):
            items = grouped[(term["key"], course["key"])]
            if not items:
                continue
            attainment = _mean([float(item["attainment"]) for item in items])
            target = _mean([float(item["target"]) for item in items])
            gap = _mean(
                [float(item["attainment"]) - float(item["target"]) for item in items]
            )
            attainments[course_index, term_index] = attainment
            gaps[course_index, term_index] = gap
            counts[course_index, term_index] = len(items)
            cells.append(
                {
                    "row_label": course_label,
                    "term_label": term["label"],
                    "term_index": term_index,
                    "attainment": attainment,
                    "target": target,
                    "gap": gap,
                }
            )
    insights = _matrix_insights(
        analysis,
        cells,
        possible_cells=len(courses) * len(terms),
        cell_label="course-term cells",
    )
    return _target_gap_heatmap(
        analysis,
        pyplot,
        title=title,
        row_labels=[item["label"].split(" — ", 1)[0] for item in courses],
        term_labels=[item["label"] for item in terms],
        attainments=attainments,
        gaps=gaps,
        counts=counts,
        insights=insights,
    )


def _campus_comparison_chart(analysis: dict[str, Any], pyplot) -> dict[str, Any]:
    title = "Edinburg and Brownsville attainment comparison"
    comparison = analysis["campus_comparison"]
    if comparison["status"] != "available":
        return _unavailable(
            title,
            comparison["reason"]
            or "At least one usable measure from each campus is required.",
        )
    groups = comparison["groups"]
    if not groups:
        return _unavailable(title, "No campus evidence groups are available in this selection.")
    # Keep an ABET-visit figure legible while retaining the exact full table in
    # the page. The first rows use the configured/chronological group order.
    displayed = groups[:18]
    figure, axis = pyplot.subplots(
        figsize=(9.2, max(3.8, 0.46 * len(displayed) + 1.9))
    )
    y_positions = np.arange(len(displayed), dtype=float)
    campus_styles = {
        "Edinburg": {"color": "#003638", "marker": "o"},
        "Brownsville": {"color": "#ee7f2f", "marker": "D"},
    }
    labeled_campuses: set[str] = set()
    for row_index, group in enumerate(displayed):
        edinburg = group["campuses"]["Edinburg"]
        brownsville = group["campuses"]["Brownsville"]
        if edinburg and brownsville:
            axis.plot(
                [edinburg["mean"], brownsville["mean"]],
                [row_index, row_index],
                color="#c4ced4",
                linewidth=1.5,
                zorder=1,
            )
        for campus in CAMPUS_ORDER:
            values = group["campuses"][campus]
            if not values:
                continue
            style = campus_styles[campus]
            axis.scatter(
                values["mean"],
                row_index,
                color=style["color"],
                marker=style["marker"],
                s=54,
                edgecolors="white",
                linewidths=0.65,
                zorder=3,
                label=campus if campus not in labeled_campuses else None,
            )
            labeled_campuses.add(campus)
            axis.scatter(
                values["target"],
                row_index,
                color=style["color"],
                marker="|",
                s=145,
                linewidths=1.5,
                alpha=0.75,
                zorder=2,
            )
    axis.set_yticks(
        y_positions,
        [str(group["label"]).split(" — ", 1)[0] for group in displayed],
    )
    axis.invert_yaxis()
    axis.set_xlim(0, 100)
    axis.set_xlabel("Mean attainment (%) · slim ticks show each campus mean target")
    axis.set_title(title, loc="left", weight="bold")
    axis.grid(axis="x", alpha=0.18)
    for spine in ("top", "right", "left"):
        axis.spines[spine].set_visible(False)
    handles, labels = axis.get_legend_handles_labels()
    if handles:
        axis.legend(handles, labels, frameon=False, loc="lower right")

    summaries = {item["label"]: item for item in analysis["campuses"]}
    edinburg = summaries["Edinburg"]
    brownsville = summaries["Brownsville"]
    insights = [
        f"Edinburg mean attainment is {edinburg['mean']:.1f}% across {edinburg['count']} measures; "
        f"Brownsville is {brownsville['mean']:.1f}% across {brownsville['count']} measures.",
        f"Brownsville minus Edinburg is {comparison['attainment_difference']:+.1f} attainment points "
        f"and {comparison['target_gap_difference']:+.1f} points after subtracting each measure's configured target.",
        f"{comparison['comparable_group_count']} of {comparison['group_count']} "
        f"{comparison['group_dimension']} groups contain evidence from both campuses.",
    ]
    if len(groups) > len(displayed):
        insights.append(
            f"The chart shows the first {len(displayed)} groups; the exact table contains all {len(groups)}."
        )
    alt = (
        "Paired-dot campus comparison. Navy circles represent Edinburg, orange diamonds "
        "represent Brownsville, and slim ticks represent each campus's configured target. "
        + " ".join(insights)
    )
    return _chart(
        figure,
        title=title,
        alt_text=alt,
        pyplot=pyplot,
        chart_type="campus_comparison",
        insights=insights,
        metadata={
            "group_dimension": comparison["group_dimension"],
            "group_count": comparison["group_count"],
            "comparable_group_count": comparison["comparable_group_count"],
            "campuses": list(CAMPUS_ORDER),
        },
    )


def _bloom_chart(analysis: dict[str, Any], pyplot) -> dict[str, Any]:
    title = "Bloom-level attainment distribution"
    groups: dict[str, list[float]] = defaultdict(list)
    for row in analysis["rows"]:
        if row["bloom_level"] != "Unspecified":
            groups[row["bloom_level"]].append(float(row["attainment"]))
    levels = sorted(
        groups,
        key=lambda value: (_BLOOM_RANK.get(value, len(BLOOM_ORDER)), value),
    )
    if not levels:
        return _unavailable(title, "No records with a Bloom level are available in this selection.")
    figure, axis = pyplot.subplots(figsize=(max(7.5, 1.08 * len(levels)), 5.1))
    boxplot_options = {
        "patch_artist": True,
        "showmeans": True,
        "meanprops": {
            "marker": "D",
            "markerfacecolor": "#15212b",
            "markeredgecolor": "white",
            "markersize": 5,
        },
    }
    try:
        plot = axis.boxplot(
            [groups[level] for level in levels],
            tick_labels=levels,
            **boxplot_options,
        )
    except TypeError:  # Matplotlib 3.8 used ``labels`` before ``tick_labels``.
        plot = axis.boxplot(
            [groups[level] for level in levels],
            labels=levels,
            **boxplot_options,
        )
    for index, box in enumerate(plot["boxes"]):
        box.set_facecolor(_COLORS[index % len(_COLORS)])
        box.set_alpha(0.72)
    mean_target = _mean([float(row["target"]) for row in analysis["rows"]])
    axis.axhline(mean_target, color="#b94747", linestyle="--", linewidth=1.2, label=f"Mean target {mean_target:.1f}%")
    kw = analysis["kruskal_wallis"]
    annotation = (
        f"Kruskal–Wallis p = {kw['p_value']:.4f}"
        if kw["status"] == "available"
        else "Kruskal–Wallis not computable"
    )
    axis.text(0.99, 0.02, annotation, transform=axis.transAxes, ha="right", va="bottom", fontsize=8)
    axis.set_ylim(0, max(100.0, max(value for values in groups.values() for value in values) + 5))
    axis.set_ylabel("Attainment (%)")
    axis.set_title(title, loc="left", weight="bold")
    axis.grid(axis="y", alpha=0.2)
    axis.legend(loc="lower left", frameon=False)
    alt = "; ".join(
        f"{level}: {len(groups[level])} measures, median {median(groups[level]):.1f}%"
        for level in levels
    )
    return _chart(figure, title=title, alt_text=alt, pyplot=pyplot)


def _heatmap_chart(analysis: dict[str, Any], pyplot) -> dict[str, Any]:
    title = "Course and student-outcome attainment matrix"
    rows = analysis["rows"]
    courses = analysis["courses"]
    outcomes = analysis["outcomes"]
    if not rows or not courses or not outcomes:
        return _unavailable(title, "Course-and-outcome evidence is not available in this selection.")
    grouped: dict[tuple[Any, Any], list[float]] = defaultdict(list)
    for row in rows:
        grouped[(row.get("course_id"), row.get("outcome_id"))].append(float(row["attainment"]))
    matrix = np.full((len(courses), len(outcomes)), np.nan)
    for course_index, course in enumerate(courses):
        for outcome_index, outcome in enumerate(outcomes):
            values = grouped[(course["key"], outcome["key"])]
            if values:
                matrix[course_index, outcome_index] = _mean(values)
    figure, axis = pyplot.subplots(
        figsize=(max(7.2, 1.05 * len(outcomes) + 3), max(3.4, 0.48 * len(courses) + 1.8))
    )
    cmap = pyplot.get_cmap("RdYlGn").with_extremes(bad="#eef2f4")
    image = axis.imshow(matrix, vmin=0, vmax=100, aspect="auto", cmap=cmap)
    axis.set_xticks(
        np.arange(len(outcomes)),
        [item["label"].split(":", 1)[0] for item in outcomes],
    )
    axis.set_yticks(
        np.arange(len(courses)),
        [item["label"].split(" — ", 1)[0] for item in courses],
    )
    for course_index in range(len(courses)):
        for outcome_index in range(len(outcomes)):
            value = matrix[course_index, outcome_index]
            axis.text(
                outcome_index,
                course_index,
                "—" if np.isnan(value) else f"{value:.1f}",
                ha="center",
                va="center",
                fontsize=8,
                color="#15212b",
            )
    axis.set_title(title, loc="left", weight="bold")
    figure.colorbar(image, ax=axis, label="Attainment (%)", shrink=0.82)
    populated = int(np.count_nonzero(~np.isnan(matrix)))
    alt = f"Matrix with {len(courses)} courses, {len(outcomes)} outcomes, and {populated} populated course-outcome cells."
    return _chart(figure, title=title, alt_text=alt, pyplot=pyplot)


def _indicator_chart(analysis: dict[str, Any], pyplot) -> dict[str, Any]:
    title = "Performance indicator and Bloom attainment by term"
    rows = analysis["rows"]
    terms = analysis["terms"]
    if not rows or not terms:
        return _unavailable(title, "No performance-indicator evidence is available in this selection.")

    def natural_key(value: Any) -> tuple[tuple[int, Any], ...]:
        """Sort PI-2 before PI-10 while keeping arbitrary program codes stable."""
        return tuple(
            (1, int(part)) if part.isdigit() else (0, part.casefold())
            for part in re.split(r"(\d+)", str(value or ""))
            if part
        )

    def short_term(label: str) -> str:
        parts = label.split()
        if len(parts) >= 2 and parts[-1].isdigit():
            season = {
                "fall": "F",
                "spring": "Sp",
                "summer": "Su",
                "winter": "W",
            }.get(parts[0].casefold(), parts[0][:2])
            return f"{season}{parts[-1][-2:]}"
        return label

    panel_rows: dict[tuple[Any, Any], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        panel_rows[(row.get("outcome_id"), row.get("indicator_id"))].append(row)

    def panel_sort_key(item: tuple[tuple[Any, Any], list[dict[str, Any]]]):
        first = item[1][0]
        return (
            _number(first.get("outcome_order")) or 0,
            natural_key(first.get("outcome_code") or ""),
            natural_key(first.get("indicator_code") or first.get("indicator_label")),
        )

    panels = sorted(panel_rows.items(), key=panel_sort_key)
    term_index = {term["key"]: index for index, term in enumerate(terms)}
    term_labels = [str(term["label"]) for term in terms]
    bloom_levels = sorted(
        {str(row["bloom_level"]) for row in rows},
        key=lambda level: (_BLOOM_RANK.get(level, len(BLOOM_ORDER)), level),
    )
    bloom_colors = {
        "Remember": "#4477aa",
        "Understand": "#66ccee",
        "Apply": "#228833",
        "Analyze": "#ee7733",
        "Evaluate": "#aa3377",
        "Create": "#ccbb44",
        "Unspecified": "#707980",
    }
    markers = ("o", "s", "^", "D", "P", "X", "v", "<", ">")
    bloom_styles = {
        level: {
            "color": bloom_colors.get(level, _COLORS[index % len(_COLORS)]),
            "marker": markers[index % len(markers)],
        }
        for index, level in enumerate(bloom_levels)
    }

    column_count = min(3, len(panels))
    row_count = math.ceil(len(panels) / column_count)
    figure, axes = pyplot.subplots(
        row_count,
        column_count,
        figsize=(max(7.8, 4.05 * column_count), max(4.4, 3.25 * row_count)),
        sharex=True,
        sharey=True,
        squeeze=False,
    )
    flat_axes = list(axes.flat)
    for unused in flat_axes[len(panels) :]:
        figure.delaxes(unused)
    flat_axes = flat_axes[: len(panels)]

    all_scale_values = [float(row["attainment"]) for row in rows] + [
        float(row["target"]) for row in rows
    ]
    lower = max(0.0, 5.0 * math.floor((min(all_scale_values) - 5.0) / 5.0))
    upper = min(100.0, 5.0 * math.ceil((max(all_scale_values) + 5.0) / 5.0))
    if upper - lower < 30.0:
        padding = (30.0 - (upper - lower)) / 2.0
        lower = max(0.0, lower - padding)
        upper = min(100.0, upper + padding)
        if upper - lower < 30.0:
            lower = max(0.0, upper - 30.0)

    multiple_outcomes = len({key[0] for key, _ in panels}) > 1
    panel_metadata: list[dict[str, Any]] = []
    observed_panel_terms = 0
    latest_results: list[tuple[str, float, float]] = []
    available_slopes: list[tuple[str, float]] = []
    legend_handles: dict[str, Any] = {}

    for axis, (panel_key, items) in zip(flat_axes, panels):
        outcome_id, indicator_id = panel_key
        first = items[0]
        outcome_code = str(first.get("outcome_code") or "Outcome")
        indicator_code = _display_indicator_code(
            first.get("indicator_code") or first.get("indicator_label")
        )
        panel_label = (
            f"{outcome_code} · {indicator_code}" if multiple_outcomes else indicator_code
        )

        by_term: dict[Any, list[dict[str, Any]]] = defaultdict(list)
        by_term_bloom: dict[tuple[Any, str], list[dict[str, Any]]] = defaultdict(list)
        for item in items:
            by_term[item.get("term_id")].append(item)
            by_term_bloom[(item.get("term_id"), str(item["bloom_level"]))].append(item)

        point_count = 0
        for level in bloom_levels:
            style = bloom_styles[level]
            level_x: list[float] = []
            level_y: list[float] = []
            for term in terms:
                evidence = by_term_bloom[(term["key"], level)]
                if evidence:
                    level_x.append(float(term_index[term["key"]]))
                    level_y.append(
                        _mean([float(item["attainment"]) for item in evidence])
                    )
            if level_x:
                plotted = axis.scatter(
                    level_x,
                    level_y,
                    s=34,
                    marker=style["marker"],
                    color=style["color"],
                    edgecolors="white",
                    linewidths=0.55,
                    alpha=0.9,
                    zorder=3,
                    label=level,
                )
                legend_handles.setdefault(level, plotted)
                point_count += len(level_x)

        observed_x: list[float] = []
        observed_means: list[float] = []
        target_values: list[float | None] = []
        for term in terms:
            evidence = by_term[term["key"]]
            if not evidence:
                target_values.append(None)
                continue
            observed_x.append(float(term_index[term["key"]]))
            observed_means.append(
                _mean([float(item["attainment"]) for item in evidence])
            )
            target_values.append(_mean([float(item["target"]) for item in evidence]))
        observed_panel_terms += len(observed_x)
        axis.scatter(
            observed_x,
            observed_means,
            s=64,
            marker="o",
            facecolors="none",
            edgecolors="#15212b",
            linewidths=1.5,
            zorder=4,
        )

        observed_targets = [value for value in target_values if value is not None]
        if observed_targets:
            if len({round(value, 10) for value in observed_targets}) == 1:
                axis.hlines(
                    observed_targets[0],
                    min(observed_x) - 0.35,
                    max(observed_x) + 0.35,
                    color="#b94747",
                    linestyle="--",
                    linewidth=1.25,
                    zorder=1,
                )
            else:
                axis.plot(
                    observed_x,
                    observed_targets,
                    color="#b94747",
                    linestyle="--",
                    linewidth=1.25,
                    zorder=1,
                )
            latest_results.append(
                (panel_label, observed_means[-1], observed_targets[-1])
            )

        trend_status = "unavailable"
        slope: float | None = None
        trend_reason: str | None = None
        is_unmapped = indicator_code == "Unmapped source PI"
        if is_unmapped:
            trend_reason = "Unmapped source rows may combine distinct indicators."
        elif len(observed_x) >= 3:
            slope, intercept = np.polyfit(observed_x, observed_means, 1)
            fitted_x = np.linspace(min(observed_x), max(observed_x), 80)
            axis.plot(
                fitted_x,
                slope * fitted_x + intercept,
                color="#173f5f",
                linewidth=2.1,
                zorder=2,
            )
            slope = float(slope)
            trend_status = "available"
            available_slopes.append((panel_label, slope))
        elif len(observed_x) == 2:
            axis.plot(
                observed_x,
                observed_means,
                color="#173f5f",
                linestyle=":",
                linewidth=1.5,
                zorder=2,
            )
            trend_reason = "Two-term change shown; three terms are required for a trend."
        else:
            trend_reason = "Only one populated term; a trend is not available."

        if trend_status == "available":
            annotation = (
                f"{slope:+.1f} points/term · {len(observed_x)} terms · "
                f"{len(items)} measures"
            )
        elif len(observed_x) == 2:
            change = observed_means[-1] - observed_means[0]
            annotation = f"{change:+.1f} two-term change · {len(items)} measures"
        else:
            annotation = f"Trend unavailable · {len(items)} measure{'s' if len(items) != 1 else ''}"
        axis.text(
            0.03,
            0.04,
            annotation,
            transform=axis.transAxes,
            fontsize=7.3,
            color="#40515e",
            va="bottom",
        )
        axis.set_title(panel_label, fontsize=10.5, weight="bold")
        axis.set_ylim(lower, upper)
        axis.set_xticks(
            np.arange(len(terms), dtype=float),
            [short_term(label) for label in term_labels],
            rotation=38,
            ha="right",
            fontsize=7.5,
        )
        axis.tick_params(axis="y", labelsize=8)
        axis.grid(axis="y", alpha=0.18)
        for spine in ("top", "right"):
            axis.spines[spine].set_visible(False)

        panel_metadata.append(
            {
                "outcome_code": outcome_code,
                "indicator_code": indicator_code,
                "point_count": point_count,
                "measure_count": len(items),
                "term_labels": term_labels,
                "target_values": target_values,
                "target_label": "Configured target by term",
                "trend": {
                    "status": trend_status,
                    "slope": slope,
                    "reason": trend_reason,
                },
            }
        )

    for index, axis in enumerate(flat_axes):
        if index % column_count == 0:
            axis.set_ylabel("Attainment (%)", fontsize=9)
    if legend_handles:
        figure.legend(
            [legend_handles[level] for level in bloom_levels if level in legend_handles],
            [level for level in bloom_levels if level in legend_handles],
            title="Bloom level",
            loc="lower center",
            bbox_to_anchor=(0.5, 0.005),
            ncol=min(7, len(legend_handles)),
            frameon=False,
            fontsize=8,
            title_fontsize=8,
        )
    figure.suptitle(
        "PI-wise descriptive attainment trends",
        x=0.5,
        y=0.995,
        fontsize=14,
        weight="bold",
    )

    possible_panel_terms = len(panels) * len(terms)
    missing_panel_terms = possible_panel_terms - observed_panel_terms
    insights = [
        f"{len(panels)} performance-indicator panel{'s' if len(panels) != 1 else ''} "
        f"show observed Bloom-level results and target-relative trends across {len(terms)} terms.",
        f"Evidence covers {observed_panel_terms} of {possible_panel_terms} possible indicator-term cells; "
        f"{missing_panel_terms} have no evidence.",
    ]
    if latest_results:
        latest_met = sum(value >= target for _, value, target in latest_results)
        insights.append(
            f"In each indicator's latest observed term, {latest_met} of {len(latest_results)} "
            "indicator means met their configured targets."
        )
        shortfalls = [
            (target - value, label, value, target)
            for label, value, target in latest_results
            if value < target
        ]
        if shortfalls:
            gap, label, value, target = max(shortfalls)
            insights.append(
                f"The largest latest shortfall is {label}: {value:.1f}% versus a "
                f"{target:.1f}% target ({gap:.1f} points below)."
            )
    if available_slopes:
        label, slope = min(available_slopes, key=lambda item: item[1])
        direction = "declining" if slope < -0.05 else "rising" if slope > 0.05 else "stable"
        insights.append(
            f"The most downward fitted pattern is {label}, {direction} at {slope:+.1f} percentage points per term."
        )
    if any(row.get("status") != "approved" for row in rows):
        insights.insert(0, "Preview includes records that are not approved for official reporting.")

    metadata = {
        "facet_by": "performance_indicator",
        "panel_count": len(panels),
        "panels": panel_metadata,
        "term_labels": term_labels,
        "legend_title": "Bloom level",
        "bloom_levels": bloom_levels,
        "bloom_styles": bloom_styles,
        "target_mode": "configured_by_term",
    }
    alt = (
        f"Faceted performance-indicator chart with {len(panels)} panels. Colored symbols "
        "show observed Bloom-level term means; outlined points show overall indicator means, "
        "solid lines show descriptive trends where at least three terms are available, and "
        "dashed red lines show configured targets. "
        + " ".join(insights)
    )
    return _chart(
        figure,
        title=title,
        alt_text=alt,
        pyplot=pyplot,
        chart_type="faceted_pi_trend",
        insights=insights,
        metadata=metadata,
        layout_rect=(0.0, 0.055, 1.0, 0.955),
    )


def _trend_chart(analysis: dict[str, Any], pyplot) -> dict[str, Any]:
    title = "Chronological attainment trend"
    trend = analysis["trend"]
    if trend["status"] != "available":
        return _unavailable(title, trend["reason"] or "A trend could not be computed.")
    terms = trend["terms"]
    x = np.arange(len(terms), dtype=float)
    observed = [float(item["mean"]) for item in terms]
    fitted = [float(item["fitted"]) for item in terms]
    figure, axis = pyplot.subplots(figsize=(8.5, 4.8))
    axis.scatter(x, observed, color="#ee7f2f", s=55, zorder=3, label="Observed term mean")
    axis.plot(x, observed, color="#ee7f2f", alpha=0.35, linewidth=1)
    axis.plot(x, fitted, color="#003638", linewidth=2.2, label="Linear trend")
    mean_target = _mean([float(row["target"]) for row in analysis["rows"]])
    axis.axhline(mean_target, color="#b94747", linestyle="--", linewidth=1.2, label=f"Mean target {mean_target:.1f}%")
    axis.set_xticks(x, [item["label"] for item in terms], rotation=35, ha="right")
    axis.set_ylim(0, max(100.0, max(observed + fitted) + 5))
    axis.set_ylabel("Attainment (%)")
    axis.set_title(title, loc="left", weight="bold")
    axis.grid(axis="y", alpha=0.2)
    axis.legend(frameon=False)
    axis.text(
        0.99,
        0.02,
        f"slope {trend['slope']:+.2f} points / configured term unit; p = {trend['p_value']:.4f}",
        transform=axis.transAxes,
        ha="right",
        va="bottom",
        fontsize=8,
    )
    alt = (
        f"{trend['direction'].title()} linear trend across {len(terms)} terms with slope "
        f"{trend['slope']:+.2f}; "
        + "; ".join(f"{item['label']} {item['mean']:.1f}%" for item in terms)
    )
    return _chart(figure, title=title, alt_text=alt, pyplot=pyplot)


def generate_charts(
    rows: Iterable[Any],
    selected_courses: Iterable[Any] | None = None,
    approved_only: bool = False,
    statuses: Iterable[str] | None = None,
    campus_group: str = "term",
) -> dict[str, dict[str, Any]]:
    """Render PNG data URIs plus text alternatives for the selected evidence."""
    import matplotlib

    matplotlib.use("Agg", force=True)
    from matplotlib import pyplot

    analysis = analyze_rows(
        rows,
        selected_courses=selected_courses,
        approved_only=approved_only,
        statuses=statuses,
        campus_group=campus_group,
    )
    return {
        "course_attainment": _course_chart(analysis, pyplot),
        "semester_course": _semester_course_chart(analysis, pyplot),
        "campus_comparison": _campus_comparison_chart(analysis, pyplot),
        "semester_indicator": _indicator_chart(analysis, pyplot),
        "bloom_boxplot": _bloom_chart(analysis, pyplot),
        "trend_line": _trend_chart(analysis, pyplot),
        "course_outcome_heatmap": _heatmap_chart(analysis, pyplot),
    }
