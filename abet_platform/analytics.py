"""Pure analytics helpers used by dashboards and exports."""

from __future__ import annotations

from collections import defaultdict


def attainment_percent(levels) -> float:
    rows = list(levels)
    try:
        percentages = [level["level_percent"] for level in rows]
    except (KeyError, IndexError):
        percentages = []
    if rows and percentages and all(value is not None for value in percentages):
        attained_percent = sum(
            float(value)
            for level, value in zip(rows, percentages, strict=True)
            if int(level["is_attained"])
        )
        return round(attained_percent, 1)
    total = sum(int(level["student_count"]) for level in rows)
    attained = sum(
        int(level["student_count"]) for level in rows if int(level["is_attained"])
    )
    return round((attained / total) * 100, 1) if total else 0.0


def summarize_records(rows) -> dict:
    records = list(rows)
    approved = [r for r in records if r["status"] == "approved"]
    met = [r for r in approved if r["attainment"] >= r["target"]]
    return {
        "total": len(records),
        "draft": sum(r["status"] in {"draft", "returned"} for r in records),
        "submitted": sum(r["status"] == "submitted" for r in records),
        "approved": len(approved),
        "met": len(met),
        "met_rate": round(len(met) / len(approved) * 100, 1) if approved else 0,
        "average": round(sum(r["attainment"] for r in approved) / len(approved), 1)
        if approved
        else 0,
    }


def aggregate(rows, dimension: str) -> list[dict]:
    grouped: dict[tuple, list] = defaultdict(list)
    for row in rows:
        grouped[(row[f"{dimension}_id"], row[f"{dimension}_label"])].append(row)
    result = []
    for (entity_id, label), items in grouped.items():
        approved = [r for r in items if r["status"] == "approved"]
        raw_average = (
            sum(float(r["attainment"]) for r in approved) / len(approved)
            if approved else None
        )
        average = round(raw_average, 1) if raw_average is not None else None
        target_source = approved or items
        raw_target = sum(float(r["target"]) for r in target_source) / len(target_source)
        target = round(raw_target, 1)
        result.append(
            {
                "id": entity_id,
                "label": label,
                "count": len(items),
                "approved": len(approved),
                "average": average,
                "target": target,
                "met": raw_average is not None and raw_average >= raw_target,
            }
        )
    return sorted(result, key=lambda item: item["label"])
