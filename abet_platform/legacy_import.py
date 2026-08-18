"""Idempotent import of UTRGV legacy percentages into reviewable evidence."""

from __future__ import annotations

import hashlib
import math
import sqlite3

from .legacy_reader import list_records, source_metadata


def _clean(value) -> str:
    return str(value or "").replace("\u00a0", " ").strip()


def _pi_parts(value) -> tuple[str, str]:
    text = _clean(value).replace("‑", "-")
    if not text:
        return "UNMAPPED", "Unmapped source PI — administrator review required"
    if ":" in text:
        code, description = text.split(":", 1)
        return code.strip(), description.strip()
    return text[:40], text


def _scaled_counts(percentages: list[float]) -> list[int]:
    cleaned = [max(0.0, float(value or 0)) for value in percentages]
    total = sum(cleaned)
    if total <= 0:
        return [0, 0, 0, 10_000]
    normalized = [value / total * 10_000 for value in cleaned]
    counts = [int(round(value)) for value in normalized]
    counts[max(range(4), key=lambda index: normalized[index])] += 10_000 - sum(counts)
    return counts


def _indicator_for(db: sqlite3.Connection, outcome_id: int, raw_pi) -> int:
    code, description = _pi_parts(raw_pi)
    exact = db.execute(
        """SELECT id FROM performance_indicators
           WHERE outcome_id=? AND LOWER(description)=LOWER(?) LIMIT 1""",
        (outcome_id, description),
    ).fetchone()
    if exact:
        return exact["id"]
    same_code = db.execute(
        """SELECT id,description FROM performance_indicators
           WHERE outcome_id=? AND REPLACE(code,'‑','-')=? COLLATE NOCASE LIMIT 1""",
        (outcome_id, code),
    ).fetchone()
    if same_code and _clean(same_code["description"]).casefold() == description.casefold():
        return same_code["id"]
    digest = hashlib.sha256(f"{code}|{description}".encode()).hexdigest()[:8].upper()
    alias_code = f"{code}-L{digest}"[:40]
    return db.execute(
        """INSERT INTO performance_indicators(outcome_id,code,description,display_order,is_active)
           VALUES (?,?,?,99,0)
           ON CONFLICT(outcome_id,code) DO UPDATE SET description=excluded.description
           RETURNING id""",
        (outcome_id, alias_code, description),
    ).fetchone()["id"]


def import_legacy_records(
    db: sqlite3.Connection,
    source,
    *,
    program_id: int,
    imported_by: int,
    campus: str = "Unassigned",
    source_key: str | None = None,
) -> dict[str, int | str]:
    """Import unseen rows as immutable percentage-basis drafts.

    The source schema never stored sample size or collector identity. Exact REAL
    percentages are stored on each assessment result; scaled counts remain only
    for backward-compatible readers. Imported records are deliberately drafts
    until reviewed.
    """
    metadata = source_metadata(source)
    # The content digest changes when new rows are added. Use a stable, program-
    # scoped source key for idempotency and return the content digest for audit.
    if campus not in {"Edinburg", "Brownsville", "Unassigned"}:
        raise ValueError("Legacy campus must be Edinburg or Brownsville.")
    identity = source_key or str(metadata["filename"])
    fingerprint = hashlib.sha256(
        f"utrgv-legacy:{campus}:{identity}".encode()
    ).hexdigest()
    content_fingerprint = str(metadata["sha256"])
    program = db.execute("SELECT * FROM programs WHERE id=?", (program_id,)).fetchone()
    if not program:
        raise ValueError("Target program was not found.")
    rub = db.execute(
        "SELECT id FROM rubrics WHERE program_id=? AND name='EPAN' COLLATE NOCASE", (program_id,)
    ).fetchone()
    if not rub:
        raise ValueError("The UTRGV program requires the EPAN rubric before import.")
    levels = db.execute(
        "SELECT id,label FROM rubric_levels WHERE rubric_id=? ORDER BY display_order", (rub["id"],)
    ).fetchall()
    if [row["label"].casefold() for row in levels] != ["expert", "practitioner", "apprentice", "novice"]:
        raise ValueError("The EPAN rubric levels do not match the legacy distribution.")
    courses = {row["code"].casefold(): row for row in db.execute("SELECT id,code FROM courses WHERE program_id=?", (program_id,))}
    terms = {row["name"].casefold(): row for row in db.execute("SELECT id,name FROM academic_terms WHERE program_id=?", (program_id,))}
    outcomes = {row["code"].casefold(): row for row in db.execute("SELECT id,code FROM outcomes WHERE program_id=?", (program_id,))}

    imported = skipped = 0
    page = 1
    while True:
        batch = list_records(source, page=page, per_page=200)
        for source_row in batch["records"]:
            source_id = int(source_row["id"])
            if db.execute(
                """SELECT 1 FROM legacy_import_items
                   WHERE program_id=? AND source_fingerprint=? AND source_record_id=?""",
                (program_id, fingerprint, source_id),
            ).fetchone():
                skipped += 1
                continue
            course = courses.get(_clean(source_row["course"]).casefold())
            term = terms.get(_clean(source_row["semester"]).casefold())
            outcome = outcomes.get(_clean(source_row["slo"]).casefold())
            if not course or not term or not outcome:
                raise ValueError(f"Source row {source_id} references an unconfigured course, term, or outcome.")
            indicator_id = _indicator_for(db, outcome["id"], source_row["pi"])
            percentages = [
                float(source_row["expert"] or 0),
                float(source_row["practitioner"] or 0),
                float(source_row["apprentice"] or 0),
                float(source_row["novice"] or 0),
            ]
            if any(not math.isfinite(value) or value < 0 or value > 100 for value in percentages):
                raise ValueError(f"Source row {source_id} has an out-of-range EPAN value.")
            if abs(sum(percentages) - 100) > 0.05:
                raise ValueError(f"Source row {source_id} has an invalid EPAN distribution.")
            assessment_id = db.execute(
                """INSERT INTO assessment_records
                   (program_id,term_id,course_id,outcome_id,indicator_id,rubric_id,collected_by,method,
                    assessment_tool,bloom_level,sample_size,result_basis,target,rationale,observations,action_notes,status,campus)
                   VALUES (?,?,?,?,?,?,?,'direct',?,?,NULL,'percentages',?,?,?,?, 'draft',?)""",
                (
                    program_id, term["id"], course["id"], outcome["id"], indicator_id, rub["id"], imported_by,
                    _clean(source_row["assessment_tool"]) or "Source assessment tool",
                    _clean(source_row["blooms_level"]), float(program["default_target"]),
                    _clean(source_row["explanation"]), _clean(source_row["observations"]),
                    "Current source percentage distribution. Original sample size and collector were not stored.",
                    campus,
                ),
            ).lastrowid
            counts = _scaled_counts(percentages)
            db.executemany(
                """INSERT INTO assessment_results
                   (assessment_id,rubric_level_id,student_count,level_percent)
                   VALUES (?,?,?,?)""",
                [
                    (assessment_id, level["id"], count, percent)
                    for level, count, percent in zip(
                        levels, counts, percentages, strict=True
                    )
                ],
            )
            db.execute(
                """INSERT INTO legacy_import_items
                   (program_id,source_fingerprint,source_record_id,assessment_id,
                    expert_percent,practitioner_percent,apprentice_percent,novice_percent)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (program_id, fingerprint, source_id, assessment_id, *percentages),
            )
            imported += 1
        if not batch["has_next"]:
            break
        page += 1
    return {
        "imported": imported,
        "skipped": skipped,
        "fingerprint": fingerprint,
        "content_fingerprint": content_fingerprint,
        "campus": campus,
    }
