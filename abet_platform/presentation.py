"""Read-only presentation models; no database writes or accreditation verdicts."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import re

ANALYSIS_VIEWS = (
    ("summary", "Summary"), ("courses", "Courses & trends"),
    ("indicators", "Performance indicators"), ("campus", "Campus comparison"),
    ("bloom", "Bloom & statistics"), ("records", "Source records"),
)
VIEW_CHARTS = {
    "summary": ("trend_line",),
    "courses": ("course_attainment", "semester_course", "course_outcome_heatmap"),
    "indicators": ("semester_indicator",),
    "campus": ("campus_comparison", "trend_line"),
    "bloom": ("bloom_boxplot", "trend_line"), "records": (),
}
SOURCE_FILES = {
    "submitted": "ABET_Criterion_4_2026_Isaac_Submitted.docx",
    "criterion-4b": "ABET_Criterion_4B_Revised.pdf",
    "criterion-4c": "ABET_Criterion_4C_Revised.pdf",
    "proposed": "ABET_Interventions.pdf",
    "slo1": "SLO1_Intervention.pdf", "slo2": "SLO2_Intervention.pdf",
    "slo3": "SLO3_Intervention.pdf",
}
SOURCE_IDS = {filename: key for key, filename in SOURCE_FILES.items()}


def evidence_overview(records, outcomes=(), *, restricted=False, approved_only=True):
    """Means are summaries, never a substitute for individual PI findings."""
    rows = [dict(row) for row in records if not approved_only or row["status"] == "approved"]
    grouped = {r["outcome_id"] for r in rows}
    configured = [dict(item) for item in outcomes]
    if restricted:
        configured = [item for item in configured if item["id"] in grouped]
    cards = []
    for outcome in configured:
        items = [r for r in rows if r["outcome_id"] == outcome["id"]]
        mean = sum(r["attainment"] for r in items) / len(items) if items else None
        target = sum(r["target"] for r in items) / len(items) if items else None
        below = sum(r["attainment"] < r["target"] for r in items)
        cards.append({
            "id": outcome["id"], "code": outcome["code"],
            "description": outcome["description"], "count": len(items),
            "mean": round(mean, 1) if mean is not None else None,
            "target": round(target, 1) if target is not None else None,
            "mean_met": mean is not None and mean >= target,
            "below": below,
            "status": "No evidence" if not items else (
                "Some measures below target" if below else "All measures met target"),
            "tone": "neutral" if not items else ("watch" if below else "positive"),
            "campuses": sorted({r["campus"] for r in items}),
        })
    terms = sorted({(r["term_order"], r["term_label"]) for r in rows})
    means_met = sum(c["mean_met"] for c in cards)
    below_count = sum(r["attainment"] < r["target"] for r in rows)
    direct = [r for r in rows if r["method"] == "direct"]
    indirect = [r for r in rows if r["method"] == "indirect"]
    return {
        "cards": cards, "count": len(rows), "outcome_count": len(cards),
        "covered_outcomes": sum(c["count"] > 0 for c in cards),
        "means_met": means_met, "below_count": below_count,
        "period": f"{terms[0][1]} – {terms[-1][1]}" if terms else "No matching terms",
        "campuses": sorted({r["campus"] for r in rows}),
        "direct_count": len(direct), "indirect_count": len(indirect),
        "direct_mean": round(sum(r["attainment"] for r in direct) / len(direct), 1) if direct else None,
        "indirect_mean": round(sum(r["attainment"] for r in indirect) / len(indirect), 1) if indirect else None,
        "generated_at": datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC"),
        "takeaway": (f"{below_count} of {len(rows)} {'approved' if approved_only else 'selected'} measures are below their configured targets. "
                     "Review the individual indicators before drawing a program-level conclusion.") if below_count else (
                         f"All {len(rows)} {'approved' if approved_only else 'selected'} measures in this selection meet their configured targets."
                         if rows else "No matching evidence is available in this selection."),
    }


def matched_campus_comparison(records):
    """Match observed cells, not students; equal cell weights avoid course-mix bias.

    Instrument names are only text matches. Equivalence of rubric application,
    artifacts, and populations still requires faculty judgment.
    """
    groups = defaultdict(lambda: defaultdict(list))
    for row in records:
        r = dict(row)
        if r.get("campus") not in {"Edinburg", "Brownsville"}:
            continue
        instrument = re.sub(r"\s+", " ", r.get("assessment_tool", "").strip()).casefold()
        if not instrument:
            continue
        key = (r["course_id"], r["term_id"], r["outcome_id"], r["indicator_id"],
               r.get("method"), r.get("bloom_level"), r.get("rubric_id"), instrument)
        groups[key][r["campus"]].append(r)
    cells = []
    for campus_rows in groups.values():
        if not all(c in campus_rows for c in ("Edinburg", "Brownsville")):
            continue
        first = campus_rows["Edinburg"][0]
        item = {"course": first["course_label"], "term": first["term_label"],
                "indicator": f"{first['outcome_code']} · {first['indicator_code']}",
                "instrument": first["assessment_tool"], "bloom": first["bloom_level"]}
        for campus, prefix in (("Edinburg", "edinburg"), ("Brownsville", "brownsville")):
            rows = campus_rows[campus]
            item[prefix] = sum(r["attainment"] for r in rows) / len(rows)
            item[prefix + "_count"] = len(rows)
            item[prefix + "_gap"] = sum(r["attainment"] - r["target"] for r in rows) / len(rows)
        item["difference"] = item["brownsville"] - item["edinburg"]
        cells.append(item)
    return {
        "cells": cells, "count": len(cells),
        "edinburg": sum(c["edinburg"] for c in cells) / len(cells) if cells else None,
        "brownsville": sum(c["brownsville"] for c in cells) / len(cells) if cells else None,
        "difference": sum(c["difference"] for c in cells) / len(cells) if cells else None,
    }


def paginate_records(records, query="", page=1, per_page=20):
    query = query.strip()[:200]
    fields = ("course_label", "term_label", "outcome_label", "indicator_label", "campus",
              "assessment_tool", "observations", "action_notes")
    matches = [r for r in records if not query or query.casefold() in
               " ".join(str(r[key] or "") for key in fields).casefold()]
    pages = max(1, (len(matches) + per_page - 1) // per_page)
    page = min(max(1, page), pages)
    return {"items": matches[(page - 1) * per_page:page * per_page],
            "page": page, "pages": pages, "total": len(matches), "query": query,
            "first": (page - 1) * per_page + 1 if matches else 0,
            "last": min(page * per_page, len(matches))}


def enrich_story(story):
    if not story:
        return None
    display_titles = {
        "slo6-mece3320-verified-loop": "MECE 3320 assessment",
        "slo2-concept-development-first-comparison": "Concept development",
        "slo3-audience-adaptation-mixed-comparison": "Audience adaptation",
        "slo1-problem-analysis-reassessment": "Problem analysis",
    }
    series = {
        "slo6-mece3320-verified-loop": (
            "MECE 3320 · SLO-6 attainment", [
                ("Spring 2022", 68, "Baseline"), ("Spring 2023", 71, "Rubric tightened"),
                ("Spring 2024", 69, "More complex work"), ("Spring 2025", 74, "Integrative work")]),
        "slo2-concept-development-first-comparison": (
            "PI-1 Create attainment", [
                ("Spring 2024", 65, "Baseline"), ("Spring 2025", 80, "Before deployment"),
                ("Fall 2025", 83, "First follow-up")]),
        "slo3-audience-adaptation-mixed-comparison": (
            "Presentation and writing attainment", [
                ("Spring 2024", 61, "PI-2 presentation"), ("Fall 2025", 92, "PI-2 presentation"),
                ("Fall 2025", 60, "PI-3 writing")]),
        "slo1-problem-analysis-reassessment": (
            "MECE 2302 · Pre-intervention attainment", [
                ("Spring 2022", 76, "Before deployment"), ("Spring 2023", 69, "Before deployment"),
                ("Spring 2024", 60, "Before deployment"), ("Spring 2025", 39, "Before deployment")]),
    }
    status_labels = {"verified": "Verified course-level improvement", "monitoring": "Preliminary follow-up",
                     "attention": "Mixed result · follow-up required", "open": "Awaiting reassessment"}
    for case in story["cases"]:
        case["display_title"] = display_titles.get(case["slug"], case["title"])
        case["display_status"] = status_labels.get(case["status_key"], case["status"])
        title, values = series[case["slug"]]
        case["figure"] = {"title": title, "points": [
            {"term": term, "value": value, "note": note, "x": 95 + i * 530 / max(1, len(values) - 1),
             "y": 235 - value * 1.75} for i, (term, value, note) in enumerate(values)]}
        for source in case["sources"]:
            source["source_id"] = SOURCE_IDS.get(source["document"])
            # Only the one-page intervention rubrics and verified proposal pages
            # have an unambiguous physical PDF page. Printed SSR numbers differ.
            source["page"] = 1 if source["document"].startswith("SLO") else (
                {"slo1-problem-analysis-reassessment": 2,
                 "slo2-concept-development-first-comparison": 3,
                 "slo3-audience-adaptation-mixed-comparison": 4}.get(case["slug"])
                if source["document"] == "ABET_Interventions.pdf" else None)
    for source in story["sources"]:
        source["source_id"] = SOURCE_IDS.get(source["document"])
    return story
