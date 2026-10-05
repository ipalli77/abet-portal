"""Read-only curriculum view of the supplied 2024–2026 plan and live evidence.

The plan is a transcription, not a catalog replacement or a degree audit. It
never inserts courses, rewrites course codes, or creates assessment mappings.
Only saved records establish observed SLO/PI coverage. Historical improvement
cases remain separate from those records and do not imply loop closure.
"""
from collections import defaultdict
from copy import deepcopy
import re


# Code, title, hours, curricular category. Lab pairs are split so each course
# retains its own evidence. Core choices and electives are requirement slots.
COURSE_PLAN = (
    ("MECE 1101", "Introduction to Mechanical Engineering", 1, "engineering"),
    ("MECE 1221", "Engineering Graphics", 2, "engineering"),
    ("MECE 2140", "Engineering Materials Laboratory", 1, "engineering"),
    ("MECE 2301", "Statics", 3, "engineering"),
    ("MECE 2302", "Dynamics", 3, "engineering"),
    ("MECE 2340", "Engineering Materials", 3, "engineering"),
    ("MECE 3170", "Thermal Fluids Laboratory", 1, "engineering"),
    ("MECE 3304", "System Dynamics", 3, "engineering"),
    ("MECE 3315", "Fluid Mechanics", 3, "engineering"),
    ("MECE 3320", "Measurements & Instrumentation", 3, "engineering"),
    ("MECE 3321", "Mechanics of Solids", 3, "engineering"),
    ("MECE 3335", "Thermodynamics I", 3, "engineering"),
    ("MECE 3336", "Thermodynamics II", 3, "engineering"),
    ("MECE 3360", "Heat Transfer", 3, "engineering"),
    ("MECE 3380", "Kinematics & Dynamics of Machines", 3, "engineering"),
    ("MECE 3440", "Mechanical Engineering Analysis I", 4, "engineering"),
    ("MECE 3450", "Mechanical Engineering Analysis II", 4, "engineering"),
    ("MECE 4101", "Fundamentals of Engineering", 1, "engineering"),
    ("MECE 4350", "Machine Elements", 3, "engineering"),
    ("MECE 4361", "Senior Design I", 3, "engineering"),
    ("MECE 4362", "Senior Design II", 3, "engineering"),
    ("MATH 2413", "Calculus I", 4, "math-science"),
    ("MATH 2414", "Calculus II", 4, "math-science"),
    ("MATH 2415", "Calculus III", 4, "math-science"),
    ("CHEM 1309", "Chemistry for Engineers", 3, "math-science"),
    ("CHEM 1109", "Chemistry for Engineers Laboratory", 1, "math-science"),
    ("PHYS 2425", "Engineering Physics I", 4, "math-science"),
    ("PHYS 2426", "Engineering Physics II", 4, "math-science"),
    ("MANE 3332", "Engineering Statistics", 3, "math-science"),
    ("MANE 3364", "Manufacturing Processes", 3, "engineering"),
    ("MANE 3164", "Manufacturing Processes Laboratory", 1, "engineering"),
    ("EECE 2317", "Electrical Systems", 3, "engineering"),
    ("CSCI 1380", "Introduction to Programming", 3, "core"),
    ("ENGL 1301", "Communication I", 3, "core"),
    ("PHIL 2326", "Ethics, Technology & Society", 3, "core"),
    ("POLS 2305", "Government / Political Science I", 3, "core"),
    ("POLS 2306", "Government / Political Science II", 3, "core"),
    ("Communication II", "Choose from the approved core list", 3, "core"),
    ("American History I", "Choose from the approved core list; term not visible", 3, "core"),
    ("American History II", "Choose from the approved core list", 3, "core"),
    ("Creative Arts", "Choose from the approved core list", 3, "core"),
    ("Social / Behavioral Science", "ECON 2301, SOCI 1301, or PSYC 2301", 3, "core"),
    ("Technical Elective I", "Choose from the approved ME elective list", 3, "engineering"),
    ("Technical Elective II", "Choose from the approved ME elective list", 3, "engineering"),
    ("Technical Elective III", "Choose from the approved ME elective list", 3, "engineering"),
)

# Do not silently place American History I into the cropped Summer II slot.
STUDY_PLAN = (
    ("Freshman", 42, (
        ("Fall", 14, ("MATH 2413", "CHEM 1309", "CHEM 1109", "CSCI 1380", "MECE 1101", "MECE 1221")),
        ("Spring", 15, ("MATH 2414", "PHYS 2425", "ENGL 1301", "MECE 2340", "MECE 2140")),
        ("Summer I", 6, ("MANE 3332", "Communication II")),
        ("Summer II", 7, ("MANE 3364", "MANE 3164")),
    )),
    ("Sophomore", 31, (
        ("Fall", 15, ("MATH 2415", "PHYS 2426", "MECE 3440", "MECE 2301")),
        ("Spring", 16, ("MECE 3450", "MECE 2302", "MECE 3335", "EECE 2317", "American History II")),
    )),
    ("Junior", 31, (
        ("Fall", 15, ("MECE 3321", "MECE 3304", "MECE 3315", "MECE 3380", "Social / Behavioral Science")),
        ("Spring", 16, ("MECE 3320", "MECE 3360", "MECE 3170", "MECE 4350", "Technical Elective I", "Creative Arts")),
    )),
    ("Senior", 25, (
        ("Fall", 13, ("MECE 4361", "MECE 3336", "MECE 4101", "Technical Elective II", "POLS 2305")),
        ("Spring", 12, ("MECE 4362", "Technical Elective III", "PHIL 2326", "POLS 2306")),
    )),
)

# Explicit course references in the existing, source-backed Criterion 4 cases.
# No expansion of a program-wide intervention to unnamed courses is inferred.
CASE_COURSES = {
    "slo6-mece3320-verified-loop": {"MECE 3320": "Course-level intervention"},
    "slo2-concept-development-first-comparison": {"MECE 4361": "Concept development"},
    "slo3-audience-adaptation-mixed-comparison": {"MECE 4361": "Audience adaptation"},
    "slo1-problem-analysis-reassessment": {
        "MECE 2302": "Problem analysis · trigger course",
        "MECE 3315": "Problem analysis · named follow-up",
        "MECE 3360": "Problem analysis · named follow-up",
        "MECE 3450": "Problem analysis · named follow-up",
        "MECE 4350": "Problem analysis · named follow-up",
    },
}


def _natural_key(value):
    return [int(part) if part.isdigit() else part.casefold()
            for part in re.split(r"(\d+)", value)]


def _coverage(records):
    """Keep SLO→PI pairs together; PI-1 is not unique across outcomes."""
    groups = {}
    for record in records:
        group = groups.setdefault(record["outcome_id"], {
            "id": record["outcome_id"], "code": record["outcome_code"],
            "description": record["outcome_label"], "indicators": {},
        })
        group["indicators"][record["indicator_id"]] = {
            "id": record["indicator_id"], "code": record["indicator_code"],
            "description": record["indicator_label"],
        }
    result = sorted(groups.values(), key=lambda group: _natural_key(group["code"]))
    for group in result:
        group["indicators"] = sorted(group["indicators"].values(), key=lambda pi: _natural_key(pi["code"]))
    return result


def curriculum_overview(courses, records, actions=(), story=None):
    """Build from an authorized program scope. All inputs remain unchanged."""
    courses = [dict(course) for course in courses]
    records = [dict(record) for record in records]
    database_courses = {course["code"]: course for course in courses}
    records_by_course = defaultdict(list)
    for record in records:
        records_by_course[record["course_id"]].append(record)
    references = defaultdict(list)
    for case in (story or {}).get("cases", []):
        for code, label in CASE_COURSES.get(case["slug"], {}).items():
            references[code].append({"label": label, "slug": case["slug"],
                                     "status": case.get("display_status", case["status"])})
    actions_by_course = defaultdict(list)
    for action in actions:
        if action["course_id"] and action["status"] != "cancelled":
            actions_by_course[action["course_id"]].append(dict(action))

    definitions = list(COURSE_PLAN)
    known_codes = {course[0] for course in definitions}
    # Preserve additional portal courses (including PHIL 2393) as separate rows.
    definitions.extend((course["code"], course["name"], None, "portal")
                       for course in courses if course["code"] not in known_codes)
    timing = {code: f"{year} · {term}" for year, _, terms in STUDY_PLAN
              for term, _, codes in terms for code in codes}
    rows = []
    for code, title, credits, category in definitions:
        course = database_courses.get(code)
        course_id = course["id"] if course else None
        all_records = records_by_course.get(course_id, [])
        approved = [r for r in all_records if r["status"] == "approved" and r["campus"] in ("Edinburg", "Brownsville")]
        pending = [r for r in all_records if r["status"] != "approved" or r["campus"] not in ("Edinburg", "Brownsville")]
        cases = references.get(code, [])
        linked_actions = actions_by_course.get(course_id, [])
        has_evidence = bool(all_records)
        improvement = bool(cases or linked_actions)
        rows.append({
            "code": code, "title": title, "credits": credits, "category": category,
            "id": course_id, "anchor": "course-" + re.sub(r"[^a-z0-9]+", "-", code.lower()).strip("-"),
            "timing": timing.get(code, "Term not shown" if code in known_codes else "Not in supplied plan"),
            "group": "me" if code.startswith("MECE ") else ("portal" if category == "portal" else "support"),
            "configured": course is not None, "active": bool(course and course["is_active"]),
            "assessed": has_evidence, "improvement": improvement,
            "tone": "improvement" if improvement else ("assessed" if has_evidence else "neutral"),
            "approved_count": len(approved), "pending_count": len(pending),
            "coverage": _coverage(approved), "pending_coverage": _coverage(pending),
            "campuses": sorted({r["campus"] for r in approved}),
            "cases": cases, "actions": linked_actions,
        })
    by_code = {row["code"]: row for row in rows}
    years = []
    for year, hours, terms in STUDY_PLAN:
        term_rows = []
        for term, total, codes in terms:
            entries = [deepcopy(by_code[code]) for code in codes]
            known_hours = sum(row["credits"] for row in entries)
            term_rows.append({"name": term, "credits": total, "known_credits": known_hours,
                              "unresolved_credits": total - known_hours, "courses": entries})
        years.append({"name": year, "credits": hours, "terms": term_rows})
    return {
        "rows": rows, "years": years, "by_code": by_code,
        "me_count": sum(row["group"] == "me" for row in rows),
        "assessed_count": sum(row["assessed"] for row in rows),
        "improvement_count": sum(row["improvement"] for row in rows),
        "approved_count": sum(row["approved_count"] for row in rows),
        "source_credits": sum(year["credits"] for year in years),
        "visible_credits": sum(term["known_credits"] for year in years for term in year["terms"]),
    }
