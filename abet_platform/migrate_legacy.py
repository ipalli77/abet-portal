"""One-time importer for records created by ABET_Data_Rev1.py."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from . import create_app
from .db import get_db


def _term_sort(name: str) -> int:
    parts = name.split()
    if len(parts) != 2 or not parts[1].isdigit():
        return 0
    season = {"spring": 1, "summer": 2, "fall": 3}.get(parts[0].lower(), 0)
    return int(parts[1]) * 10 + season


def _percent_counts(row) -> list[int]:
    values = [max(0.0, float(row[key] or 0)) for key in ("expert", "practitioner", "apprentice", "novice")]
    total = sum(values)
    if total <= 0:
        return [0, 0, 0, 100]
    normalized = [value / total * 100 for value in values]
    counts = [int(round(value)) for value in normalized]
    counts[max(range(4), key=lambda index: normalized[index])] += 100 - sum(counts)
    return counts


def migrate(source: Path, program_code: str) -> int:
    if not source.is_file():
        raise SystemExit(f"Legacy database not found: {source}")
    app = create_app()
    legacy = sqlite3.connect(source)
    legacy.row_factory = sqlite3.Row
    source_rows = legacy.execute("SELECT * FROM abet_entries ORDER BY id").fetchall()
    with app.app_context():
        db = get_db()
        program = db.execute(
            "SELECT * FROM programs WHERE code=? COLLATE NOCASE ORDER BY id LIMIT 1", (program_code,)
        ).fetchone()
        if not program:
            raise SystemExit(f"Configured program not found: {program_code}")
        collector = db.execute(
            """SELECT u.id FROM users u JOIN memberships m ON m.user_id=u.id
               WHERE m.organization_id=? AND m.role IN ('owner','admin') ORDER BY u.id LIMIT 1""",
            (program["organization_id"],),
        ).fetchone()
        rubric = db.execute(
            "SELECT * FROM rubrics WHERE program_id=? AND name='EPAN' COLLATE NOCASE", (program["id"],)
        ).fetchone()
        if not collector or not rubric:
            raise SystemExit("The target needs an owner/admin and an EPAN rubric.")
        levels = db.execute(
            "SELECT * FROM rubric_levels WHERE rubric_id=? ORDER BY display_order", (rubric["id"],)
        ).fetchall()
        if len(levels) != 4:
            raise SystemExit("The target EPAN rubric must have exactly four levels.")
        imported = 0
        with db:
            for row in source_rows:
                course_code = (row["course"] or "UNMAPPED").replace("\u00a0", " ").strip()
                course = db.execute(
                    "SELECT * FROM courses WHERE program_id=? AND code=? COLLATE NOCASE", (program["id"], course_code)
                ).fetchone()
                if not course:
                    course_id = db.execute(
                        "INSERT INTO courses(program_id,code,name) VALUES (?,?,?)",
                        (program["id"], course_code, row["course_name"] or course_code),
                    ).lastrowid
                else:
                    course_id = course["id"]
                term_name = (row["semester"] or "Legacy / unspecified").strip()
                term = db.execute(
                    "SELECT * FROM academic_terms WHERE program_id=? AND name=? COLLATE NOCASE", (program["id"], term_name)
                ).fetchone()
                term_id = term["id"] if term else db.execute(
                    "INSERT INTO academic_terms(program_id,name,sort_order) VALUES (?,?,?)",
                    (program["id"], term_name, _term_sort(term_name)),
                ).lastrowid
                outcome_code = (row["slo"] or "UNMAPPED").strip().upper().removeprefix("SLO") or "UNMAPPED"
                outcome = db.execute(
                    "SELECT * FROM outcomes WHERE program_id=? AND code=? COLLATE NOCASE", (program["id"], outcome_code)
                ).fetchone()
                if not outcome:
                    outcome_id = db.execute(
                        "INSERT INTO outcomes(program_id,code,description) VALUES (?,?,?)",
                        (program["id"], outcome_code, f"Imported legacy outcome {row['slo']}"),
                    ).lastrowid
                else:
                    outcome_id = outcome["id"]
                pi_text = (row["pi"] or "Imported legacy performance indicator").strip()
                pi_code = pi_text.split(":", 1)[0][:40]
                indicator = db.execute(
                    "SELECT * FROM performance_indicators WHERE outcome_id=? AND code=? COLLATE NOCASE",
                    (outcome_id, pi_code),
                ).fetchone()
                if not indicator:
                    indicator_id = db.execute(
                        "INSERT INTO performance_indicators(outcome_id,code,description) VALUES (?,?,?)",
                        (outcome_id, pi_code, pi_text.split(":", 1)[-1].strip()),
                    ).lastrowid
                else:
                    indicator_id = indicator["id"]
                assessment_id = db.execute(
                    """INSERT INTO assessment_records
                       (program_id,term_id,course_id,outcome_id,indicator_id,rubric_id,collected_by,method,
                        assessment_tool,bloom_level,sample_size,target,rationale,observations,action_notes,status)
                       VALUES (?,?,?,?,?,?,?,'direct',?,?,100,?,?,?,?, 'draft')""",
                    (program["id"], term_id, course_id, outcome_id, indicator_id, rubric["id"], collector["id"],
                     row["assessment_tool"] or "Legacy assessment", row["blooms_level"] or "",
                     program["default_target"], row["explanation"] or "", row["observations"] or "", ""),
                ).lastrowid
                db.executemany(
                    "INSERT INTO assessment_results(assessment_id,rubric_level_id,student_count) VALUES (?,?,?)",
                    [(assessment_id, level["id"], count) for level, count in zip(levels, _percent_counts(row))],
                )
                imported += 1
            db.execute(
                """INSERT INTO audit_events(organization_id,user_id,action,entity_type,details_json)
                   VALUES (?,?,'import','legacy_database',?)""",
                (program["organization_id"], collector["id"], json.dumps({"source": source.name, "rows": imported})),
            )
    legacy.close()
    return imported


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("abet_data.db"))
    parser.add_argument("--program", required=True, help="Target configured program code, e.g. BSME")
    args = parser.parse_args()
    count = migrate(args.source.resolve(), args.program)
    print(f"Imported {count} legacy assessment records as drafts.")


if __name__ == "__main__":
    main()
