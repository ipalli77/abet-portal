"""Web routes for configuration, collection, analysis, and reporting."""

from __future__ import annotations

import csv
import io
import json
import math
import mimetypes
import os
import secrets
import sqlite3
from datetime import date
from pathlib import Path
from urllib.parse import urlencode, urlparse

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from .analysis_engine import analyze_rows, generate_charts
from .analytics import aggregate, summarize_records
from .db import get_db
from .security import (
    audit,
    faculty_preview_scope_state,
    flash_validation,
    login_required,
    parse_int,
    parse_percent,
    require_program,
    role_required,
    safe_next_url,
)


bp = Blueprint("platform", __name__)
MANAGER_ROLES = {"owner", "admin", "coordinator"}
ADMIN_EDIT_ROLES = {"owner", "admin"}
UTRGV_CAMPUSES = ("Edinburg", "Brownsville")
FACULTY_VIEW_SUPPORT_NAME = "Faculty View Support"
MAX_BULK_APPROVAL_RECORDS = 2000
ALLOWED_UPLOADS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt", ".png", ".jpg", ".jpeg"
}

STANDARD_OUTCOMES = [
    ("1", "Identify, formulate, and solve complex engineering problems by applying principles of engineering, science, and mathematics."),
    ("2", "Apply engineering design to produce solutions that meet specified needs while considering public health, safety, welfare, and global, cultural, social, environmental, and economic factors."),
    ("3", "Communicate effectively with a range of audiences."),
    ("4", "Recognize ethical and professional responsibilities in engineering situations and make informed judgments considering the impact of engineering solutions."),
    ("5", "Function effectively on a team whose members provide leadership, create a collaborative and inclusive environment, establish goals, plan tasks, and meet objectives."),
    ("6", "Develop and conduct appropriate experimentation, analyze and interpret data, and use engineering judgment to draw conclusions."),
    ("7", "Acquire and apply new knowledge as needed, using appropriate learning strategies."),
]


def _normalize_utrgv_email(value: str | None) -> str:
    """Return a canonical institutional address for an approved invitation."""
    email = (value or "").strip().casefold()
    local, separator, domain = email.partition("@")
    if (
        not separator
        or not local
        or domain != "utrgv.edu"
        or "@" in domain
        or any(character.isspace() for character in email)
    ):
        raise ValueError("Use a valid @utrgv.edu faculty email address.")
    return email


def _utrgv_roster_course_campus_pairs(
    program_id: int,
) -> list[tuple[int, str]]:
    """Validate an invitation's exact course/campus authorization pairs."""
    raw_pairs = request.form.getlist("course_campus_pairs")
    if not raw_pairs:
        # Accept owner submissions from the immediately preceding course-only
        # screen during a rolling deployment.  A legacy course selection maps
        # to both campuses, matching the v11 migration's compatibility rule.
        raw_pairs = [
            f"{raw_course_id}:{campus}"
            for raw_course_id in request.form.getlist("course_ids")
            for campus in UTRGV_CAMPUSES
        ]
    if not raw_pairs:
        raise ValueError(
            "Select at least one course and campus for this faculty member."
        )
    if len(raw_pairs) > 200:
        raise ValueError("Too many course-campus permissions were selected.")
    pairs: set[tuple[int, str]] = set()
    for raw_pair in raw_pairs:
        raw_course_id, separator, raw_campus = str(raw_pair).partition(":")
        if not separator:
            raise ValueError("A course-campus permission is malformed.")
        course_id = parse_int(raw_course_id, minimum=1)
        campus = _assessment_campus(raw_campus, required=True)
        pairs.add((course_id, campus))
    course_ids = {course_id for course_id, _campus in pairs}
    placeholders = ",".join("?" for _ in course_ids)
    valid_ids = {
        row["id"]
        for row in get_db().execute(
            f"""SELECT id FROM courses
                 WHERE program_id=? AND is_active=1 AND id IN ({placeholders})""",
            (program_id, *sorted(course_ids)),
        )
    }
    if course_ids != valid_ids:
        raise ValueError(
            "Every selected course-campus permission must belong to the active UTRGV program."
        )
    campus_order = {campus: order for order, campus in enumerate(UTRGV_CAMPUSES)}
    return sorted(pairs, key=lambda pair: (pair[0], campus_order[pair[1]]))


def _csv_safe(value):
    """Prevent spreadsheet software from treating exported narrative text as a formula."""
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return f"'{value}"
    return value


def _record_query(program_id: int, where: str = "", params: tuple = ()):
    record_scope, record_scope_params = _faculty_record_scope_sql(
        program_id, "ar.course_id", "ar.campus"
    )
    sql = f"""
        SELECT ar.*,
               t.name AS term_label,
               t.sort_order AS term_order,
               c.code || ' — ' || c.name AS course_label,
               c.id AS course_id,
               c.code AS course_code,
               c.name AS course_name,
               o.code || ': ' || o.description AS outcome_label,
               o.id AS outcome_id,
               o.code AS outcome_code,
               o.display_order AS outcome_order,
               pi.code || ': ' || pi.description AS indicator_label,
               pi.id AS indicator_id,
               pi.code AS indicator_code,
               CASE WHEN support_collector.user_id IS NOT NULL
                    THEN 'Faculty View Support (support login)'
                    ELSE u.full_name END AS collector_name,
               li.id AS legacy_import_id,
               li.source_record_id AS legacy_source_record_id,
               COALESCE(result_totals.expert_percent,li.expert_percent) AS expert_percent,
               COALESCE(result_totals.practitioner_percent,li.practitioner_percent) AS practitioner_percent,
               COALESCE(result_totals.apprentice_percent,li.apprentice_percent) AS apprentice_percent,
               COALESCE(result_totals.novice_percent,li.novice_percent) AS novice_percent,
               (SELECT COUNT(*) FROM assessment_revisions rv
                 WHERE rv.assessment_id=ar.id AND rv.program_id=ar.program_id) AS admin_revision_count,
               (SELECT rv.change_note FROM assessment_revisions rv
                 WHERE rv.assessment_id=ar.id AND rv.program_id=ar.program_id
                 ORDER BY rv.created_at DESC,rv.id DESC LIMIT 1) AS admin_change_note,
               (SELECT rv.changed_by_name FROM assessment_revisions rv
                 WHERE rv.assessment_id=ar.id AND rv.program_id=ar.program_id
                 ORDER BY rv.created_at DESC,rv.id DESC LIMIT 1) AS admin_changed_by,
               (SELECT rv.created_at FROM assessment_revisions rv
                 WHERE rv.assessment_id=ar.id AND rv.program_id=ar.program_id
                 ORDER BY rv.created_at DESC,rv.id DESC LIMIT 1) AS admin_changed_at,
               CASE
                   WHEN li.id IS NOT NULL THEN
                       li.expert_percent + li.practitioner_percent
                   WHEN ar.result_basis='percentages' THEN COALESCE(
                       result_totals.attained_percent,
                       0
                   )
                   ELSE COALESCE(
                       100.0 * result_totals.attained_count
                       / NULLIF(result_totals.total_count, 0),
                       0
                   )
               END AS attainment
          FROM assessment_records ar
          JOIN academic_terms t ON t.id = ar.term_id AND t.program_id = ar.program_id
          JOIN courses c ON c.id = ar.course_id AND c.program_id = ar.program_id
          JOIN outcomes o ON o.id = ar.outcome_id AND o.program_id = ar.program_id
          JOIN performance_indicators pi ON pi.id = ar.indicator_id AND pi.outcome_id = ar.outcome_id
          JOIN rubrics r ON r.id = ar.rubric_id AND r.program_id = ar.program_id
          JOIN users u ON u.id = ar.collected_by
          LEFT JOIN program_support_accounts support_collector
            ON support_collector.program_id=ar.program_id
           AND support_collector.user_id=ar.collected_by
          LEFT JOIN (
              SELECT rs.assessment_id,
                     rl.rubric_id,
                     SUM(CASE WHEN rl.is_attained = 1 THEN rs.student_count ELSE 0 END) AS attained_count,
                     SUM(rs.student_count) AS total_count,
                     SUM(CASE WHEN rl.is_attained = 1
                              THEN rs.level_percent END) AS attained_percent,
                     MAX(CASE WHEN LOWER(rl.label)='expert'
                              THEN rs.level_percent END) AS expert_percent,
                     MAX(CASE WHEN LOWER(rl.label)='practitioner'
                              THEN rs.level_percent END) AS practitioner_percent,
                     MAX(CASE WHEN LOWER(rl.label)='apprentice'
                              THEN rs.level_percent END) AS apprentice_percent,
                     MAX(CASE WHEN LOWER(rl.label)='novice'
                              THEN rs.level_percent END) AS novice_percent
                FROM assessment_results rs
                JOIN rubric_levels rl ON rl.id = rs.rubric_level_id
               GROUP BY rs.assessment_id, rl.rubric_id
          ) result_totals
            ON result_totals.assessment_id = ar.id AND result_totals.rubric_id = ar.rubric_id
          LEFT JOIN legacy_import_items li
            ON li.assessment_id = ar.id AND li.program_id = ar.program_id
         WHERE ar.program_id = ? {where}{record_scope}
         ORDER BY t.sort_order DESC, t.name DESC, c.code, o.display_order, pi.display_order
    """
    return get_db().execute(
        sql, (program_id, *params, *record_scope_params)
    ).fetchall()


def _faculty_course_ids(program_id: int) -> set[int] | None:
    if g.membership["role"] not in {"faculty", "reviewer"}:
        return None
    if current_app.config.get("EDITION") == "utrgv_mece":
        return {
            course_id
            for course_id, _campus in _faculty_course_campus_pairs(program_id) or set()
        }
    rows = get_db().execute(
        """SELECT ca.course_id FROM course_assignments ca
           JOIN courses c ON c.id = ca.course_id
           WHERE ca.user_id = ? AND c.program_id = ?""",
        (g.user["id"], program_id),
    ).fetchall()
    return {row["course_id"] for row in rows}


def _faculty_course_campus_pairs(
    program_id: int,
) -> set[tuple[int, str]] | None:
    """Return the active user's exact UTRGV evidence scope.

    Managers are deliberately represented by ``None`` because their program
    access is unrestricted.  An empty set means a restricted account has no
    usable course/campus authorization.
    """
    if g.membership["role"] not in {"faculty", "reviewer"}:
        return None
    if current_app.config.get("EDITION") != "utrgv_mece":
        return None
    db = get_db()
    preview = getattr(g, "faculty_preview", None)
    if preview and preview["program_id"] == program_id:
        # Never trust the request-start snapshot for a mutable support scope.
        # Re-read and validate every stored row immediately before each use so
        # another signed-in support session cannot leave stale write authority.
        current_scope = faculty_preview_scope_state(db, program_id, g.user["id"])
        if not current_scope["has_valid_scope"]:
            return set()
        return set(current_scope["pairs"])
    rows = db.execute(
        """SELECT cca.course_id,cca.campus
             FROM course_campus_assignments cca
             JOIN courses c ON c.id=cca.course_id
            WHERE cca.user_id=? AND c.program_id=?
              AND cca.campus IN ('Edinburg','Brownsville')""",
        (g.user["id"], program_id),
    ).fetchall()
    pairs = {(row["course_id"], row["campus"]) for row in rows}
    return pairs


def _faculty_record_scope_sql(
    program_id: int, course_column: str, campus_column: str
) -> tuple[str, tuple[int, ...]]:
    """Return the authoritative predicate for faculty-visible evidence rows.

    Column references are internal constants, never request input.  In the
    UTRGV edition the same authorization row must match both course and campus;
    independent ``IN`` predicates would incorrectly create a Cartesian scope.
    """
    if g.membership["role"] not in {"faculty", "reviewer"}:
        return "", ()
    if current_app.config.get("EDITION") == "utrgv_mece":
        preview = getattr(g, "faculty_preview", None)
        if preview and preview["program_id"] == program_id:
            # This predicate validates the complete support authorization state
            # in the same SQLite read snapshot that returns evidence.  It
            # cannot accidentally authorize an orphan, inactive, noncanonical,
            # or extra course-campus row that a profile loader filtered out.
            return (
                f""" AND EXISTS (
                         SELECT 1
                           FROM course_campus_assignments support_pair
                           JOIN courses support_course
                             ON support_course.id=support_pair.course_id
                            AND support_course.program_id=?
                            AND support_course.is_active=1
                           JOIN course_assignments support_assignment
                             ON support_assignment.course_id=support_pair.course_id
                            AND support_assignment.user_id=support_pair.user_id
                          WHERE support_pair.user_id=?
                            AND support_pair.course_id={course_column}
                            AND support_pair.campus={campus_column}
                            AND support_pair.campus IN ('Edinburg','Brownsville')
                     )
                     AND (SELECT COUNT(*)
                            FROM course_campus_assignments support_all_pairs
                            JOIN courses support_all_courses
                              ON support_all_courses.id=support_all_pairs.course_id
                           WHERE support_all_pairs.user_id=?
                             AND support_all_courses.program_id=?) BETWEEN 1 AND 2
                     AND NOT EXISTS (
                         SELECT 1
                           FROM course_campus_assignments support_bad_pair
                           JOIN courses support_bad_course
                             ON support_bad_course.id=support_bad_pair.course_id
                          WHERE support_bad_pair.user_id=?
                            AND support_bad_course.program_id=?
                            AND (
                                support_bad_pair.course_id<>{course_column}
                                OR support_bad_course.is_active<>1
                                OR support_bad_pair.campus NOT IN
                                   ('Edinburg','Brownsville')
                            )
                     )
                     AND (SELECT COUNT(*)
                            FROM course_assignments support_all_assignments
                            JOIN courses support_assignment_course
                              ON support_assignment_course.id=
                                 support_all_assignments.course_id
                           WHERE support_all_assignments.user_id=?
                             AND support_assignment_course.program_id=?)=1""",
                (
                    program_id,
                    g.user["id"],
                    g.user["id"],
                    program_id,
                    g.user["id"],
                    program_id,
                    g.user["id"],
                    program_id,
                ),
            )
        return (
            f""" AND EXISTS (
                     SELECT 1
                       FROM course_campus_assignments authorized_pair
                       JOIN courses authorized_course
                         ON authorized_course.id=authorized_pair.course_id
                      WHERE authorized_pair.user_id=?
                        AND authorized_pair.course_id={course_column}
                        AND authorized_pair.campus={campus_column}
                        AND authorized_course.program_id=?
                 )""",
            (g.user["id"], program_id),
        )
    return (
        f""" AND EXISTS (
                 SELECT 1
                   FROM course_assignments authorized_assignment
                   JOIN courses authorized_course
                     ON authorized_course.id=authorized_assignment.course_id
                  WHERE authorized_assignment.user_id=?
                    AND authorized_assignment.course_id={course_column}
                    AND authorized_course.program_id=?
             )""",
        (g.user["id"], program_id),
    )


def _require_current_record_access(
    program_id: int, course_id: int | None, campus: str | None
) -> None:
    """Re-check mutable exact access immediately before a record action."""
    if g.membership["role"] not in {"faculty", "reviewer"}:
        return
    if course_id is None:
        abort(403)
    if current_app.config.get("EDITION") == "utrgv_mece":
        pairs = _faculty_course_campus_pairs(program_id) or set()
        if (course_id, campus) not in pairs:
            abort(403)
        return
    allowed = _faculty_course_ids(program_id) or set()
    if course_id not in allowed:
        abort(403)


def _allowed_campuses_by_course(
    program_id: int,
) -> dict[int, tuple[str, ...]] | None:
    """Provide normalized form/filter context without weakening SQL checks."""
    if current_app.config.get("EDITION") != "utrgv_mece":
        return None
    pairs = _faculty_course_campus_pairs(program_id)
    if pairs is None:
        return None
    return {
        course_id: tuple(
            campus
            for campus in UTRGV_CAMPUSES
            if (course_id, campus) in pairs
        )
        for course_id in sorted({course_id for course_id, _campus in pairs})
    }


def _available_campuses(program_id: int) -> tuple[str, ...]:
    allowed = _allowed_campuses_by_course(program_id)
    if allowed is None:
        return UTRGV_CAMPUSES
    return tuple(
        campus
        for campus in UTRGV_CAMPUSES
        if any(campus in campuses for campuses in allowed.values())
    )


def _utrgv_roster_access_map(program_id: int) -> dict[int, dict]:
    """Return display-ready exact invitation scopes, tenant checked in SQL."""
    rows = get_db().execute(
        """SELECT frcc.faculty_roster_id,c.id AS course_id,c.code,c.name,
                  frcc.campus
             FROM faculty_roster_course_campuses frcc
             JOIN faculty_roster fr ON fr.id=frcc.faculty_roster_id
             JOIN courses c ON c.id=frcc.course_id
                           AND c.program_id=fr.program_id
            WHERE fr.program_id=?
            ORDER BY c.code,
                     CASE frcc.campus WHEN 'Edinburg' THEN 1 ELSE 2 END""",
        (program_id,),
    ).fetchall()
    grouped: dict[int, dict[int, dict]] = {}
    for row in rows:
        roster_courses = grouped.setdefault(row["faculty_roster_id"], {})
        course = roster_courses.setdefault(
            row["course_id"],
            {
                "id": row["course_id"],
                "code": row["code"],
                "name": row["name"],
                "campuses": [],
            },
        )
        course["campuses"].append(row["campus"])
    result: dict[int, dict] = {}
    for roster_id, courses_by_id in grouped.items():
        access = list(courses_by_id.values())
        pairs = {
            (course["id"], campus)
            for course in access
            for campus in course["campuses"]
        }
        summary = "; ".join(
            f"{course['code']} — {', '.join(course['campuses'])}"
            for course in access
        )
        result[roster_id] = {
            "course_campus_access": access,
            "course_campus_pairs": pairs,
            "course_campus_summary": summary,
            "course_ids_csv": ",".join(
                str(course["id"]) for course in access
            ),
            "has_course_campus_access": bool(pairs),
        }
    return result


def _enrich_utrgv_roster_rows(rows, program_id: int) -> list[dict]:
    access_by_roster = _utrgv_roster_access_map(program_id)
    enriched = []
    for row in rows:
        item = dict(row)
        access = access_by_roster.get(
            item.get("id", item.get("roster_id")),
            {
                "course_campus_access": [],
                "course_campus_pairs": set(),
                "course_campus_summary": "",
                "course_ids_csv": "",
                "has_course_campus_access": False,
            },
        )
        item.update(access)
        # Existing templates used ``courses``; keep it accurate while exposing
        # the structured access list for the campus-aware UI.
        item["courses"] = access["course_campus_summary"]
        enriched.append(item)
    return enriched


def _program_support_account(
    program_id: int,
    organization_id: int,
    *,
    user_id: int | None = None,
) -> sqlite3.Row | None:
    """Return only a non-poisoned faculty/editor support marker."""
    user_clause = " AND psa.user_id=?" if user_id is not None else ""
    params = (
        (program_id, organization_id, user_id)
        if user_id is not None
        else (program_id, organization_id)
    )
    return get_db().execute(
        f"""SELECT psa.*,u.email,u.username,u.full_name,u.is_active,
                   u.must_change_password,m.role,pm.access_level
              FROM program_support_accounts psa
              JOIN programs p ON p.id=psa.program_id
              JOIN users u ON u.id=psa.user_id
              JOIN memberships m ON m.user_id=psa.user_id
                                AND m.organization_id=p.organization_id
                                AND m.role='faculty'
              JOIN program_members pm ON pm.program_id=psa.program_id
                                     AND pm.user_id=psa.user_id
                                     AND pm.access_level='editor'
             WHERE psa.program_id=? AND p.organization_id=?{user_clause}""",
        params,
    ).fetchone()


def _support_scope_state(program_id: int, user_id: int) -> dict:
    """Summarize one support identity's stored scope and fail closed if malformed."""
    return faculty_preview_scope_state(get_db(), program_id, user_id)


def _support_account_context(program_id: int, organization_id: int) -> dict | None:
    account = _program_support_account(program_id, organization_id)
    if not account:
        return None
    item = dict(account)
    item.update(_support_scope_state(program_id, account["user_id"]))
    return item


def _load_dimensions(program_id: int) -> dict:
    db = get_db()
    return {
        "terms": db.execute(
            "SELECT * FROM academic_terms WHERE program_id = ? AND is_active = 1 ORDER BY sort_order, name",
            (program_id,),
        ).fetchall(),
        "courses": db.execute(
            "SELECT * FROM courses WHERE program_id = ? AND is_active = 1 ORDER BY code", (program_id,)
        ).fetchall(),
        "outcomes": db.execute(
            "SELECT * FROM outcomes WHERE program_id = ? AND is_active = 1 ORDER BY display_order, code",
            (program_id,),
        ).fetchall(),
        "indicators": db.execute(
            """SELECT pi.*, o.program_id FROM performance_indicators pi
               JOIN outcomes o ON o.id = pi.outcome_id
               WHERE o.program_id = ? AND pi.is_active = 1
               ORDER BY o.display_order, pi.display_order, pi.code""",
            (program_id,),
        ).fetchall(),
        "rubrics": db.execute(
            "SELECT * FROM rubrics WHERE program_id = ? ORDER BY is_default DESC, name", (program_id,)
        ).fetchall(),
    }


def _assessment_campus(value: str | None, *, required: bool) -> str:
    campus = str(value or "").strip()
    if not campus:
        if required:
            raise ValueError("Campus is required for UTRGV assessment evidence.")
        return "Unassigned"
    canonical = next(
        (item for item in UTRGV_CAMPUSES if campus.casefold() == item.casefold()),
        None,
    )
    if canonical is None:
        raise ValueError("Campus must be Edinburg or Brownsville.")
    return canonical


def _required_text(value, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} is required.")
    return text


def _owner_supplied_temporary_password() -> str:
    """Validate an owner-entered secret; support accounts never get defaults."""
    password = request.form.get("temporary_password", "")
    if len(password) < 12:
        raise ValueError("The temporary password must contain at least 12 characters.")
    if password != request.form.get("confirm_temporary_password"):
        raise ValueError("Temporary password entries do not match.")
    return password


def _support_identity_fields(
    program_id: int, *, existing_user_id: int | None = None
) -> tuple[str, str | None, str]:
    # The label is immutable server-side so evidence collected through this
    # credential can never be made to impersonate a real faculty member.
    full_name = FACULTY_VIEW_SUPPORT_NAME
    email = _normalize_utrgv_email(request.form.get("email"))
    username = request.form.get("username", "").strip() or None
    db = get_db()
    duplicate_user = db.execute(
        """SELECT id FROM users
            WHERE (email=? OR username=?
                   OR (? IS NOT NULL AND (email=? OR username=?)))
              AND id<>?""",
        (email, email, username, username, username, existing_user_id or -1),
    ).fetchone()
    if duplicate_user:
        raise ValueError("That email or sign-in name is already in use.")
    reserved_roster = db.execute(
        """SELECT 1 FROM faculty_roster fr
             JOIN programs p ON p.id=fr.program_id
            WHERE fr.approved_email=? COLLATE NOCASE
              AND p.organization_id=(
                  SELECT organization_id FROM programs WHERE id=?
              )""",
        (email, program_id),
    ).fetchone()
    if reserved_roster:
        raise ValueError(
            "That email is reserved for an approved faculty invitation."
        )
    return full_name, username, email


def _utrgv_epan_percentages(form, levels) -> list[float]:
    """Return a complete, exact EPAN percentage distribution from a form row."""
    expected = ("expert", "practitioner", "apprentice", "novice")
    if tuple(level["label"].casefold() for level in levels) != expected:
        raise ValueError("UTRGV assessment records require the EPAN rubric.")
    percentages = []
    for label in expected:
        raw_value = form.get(f"{label}_percent")
        if raw_value is None or str(raw_value).strip() == "":
            raise ValueError(f"{label.title()} percentage is required.")
        percentages.append(parse_percent(raw_value))
    if not math.isclose(math.fsum(percentages), 100.0, rel_tol=0.0, abs_tol=1e-6):
        raise ValueError(
            "Expert, Practitioner, Apprentice, and Novice percentages must total exactly 100%."
        )
    return percentages


def _validate_utrgv_record_for_review(record_id: int, program_id: int) -> None:
    """Block submit/approval when mandatory UTRGV evidence is incomplete."""
    db = get_db()
    record = db.execute(
        """SELECT ar.*,r.name AS rubric_name
           FROM assessment_records ar
           JOIN academic_terms t
             ON t.id=ar.term_id AND t.program_id=ar.program_id
           JOIN courses c
             ON c.id=ar.course_id AND c.program_id=ar.program_id
           JOIN outcomes o
             ON o.id=ar.outcome_id AND o.program_id=ar.program_id
           JOIN performance_indicators pi
             ON pi.id=ar.indicator_id AND pi.outcome_id=ar.outcome_id
           JOIN rubrics r ON r.id=ar.rubric_id AND r.program_id=ar.program_id
           WHERE ar.id=? AND ar.program_id=?""",
        (record_id, program_id),
    ).fetchone()
    if not record:
        abort(404)
    missing = [
        label
        for column, label in (
            ("campus", "Campus"),
            ("method", "Assessment method"),
            ("assessment_tool", "Assessment tool"),
            ("bloom_level", "Bloom level"),
            ("rationale", "Assessment rationale"),
            ("observations", "Observations"),
            ("action_notes", "Improvement/action notes"),
        )
        if not str(record[column] or "").strip()
    ]
    if missing:
        raise ValueError("Complete the required fields before review: " + ", ".join(missing) + ".")
    if record["campus"] not in UTRGV_CAMPUSES:
        raise ValueError("Assign this record to Edinburg or Brownsville before review.")
    if record["method"] not in {"direct", "indirect"}:
        raise ValueError("Select a valid assessment method before review.")
    if record["rubric_name"].casefold() != "epan" or record["result_basis"] != "percentages":
        raise ValueError("Enter a complete EPAN percentage distribution before review.")
    result_rows = db.execute(
        """SELECT rl.label,rs.level_percent
           FROM rubric_levels rl
           LEFT JOIN assessment_results rs
             ON rs.rubric_level_id=rl.id AND rs.assessment_id=?
           WHERE rl.rubric_id=? ORDER BY rl.display_order,rl.id""",
        (record_id, record["rubric_id"]),
    ).fetchall()
    try:
        percentages = _utrgv_epan_percentages(
            {f"{row['label'].casefold()}_percent": row["level_percent"] for row in result_rows},
            result_rows,
        )
    except ValueError as error:
        raise ValueError(f"Correct the EPAN distribution before review: {error}") from None
    if len(percentages) != 4:
        raise ValueError("Enter all four EPAN percentages before review.")


def _configured_legacy_sources() -> dict[str, dict[str, str | None]]:
    explicit = current_app.config.get("LEGACY_SOURCES") or {}
    sources: dict[str, dict[str, str | None]] = {}
    for campus in UTRGV_CAMPUSES:
        path = str(explicit.get(campus) or "").strip()
        if path:
            key = campus.casefold()
            sources[key] = {"key": key, "path": path, "campus": campus}
    if not sources:
        path = str(current_app.config.get("LEGACY_DATABASE") or "").strip()
        sources["legacy"] = {"key": "legacy", "path": path, "campus": None}
    return sources


def _analysis_filter_context(
    program_id: int,
    *,
    default_scope: str = "approved",
    include_unassigned_when_unfiltered: bool = False,
) -> dict:
    """Build one validated, authorization-aware filter for analysis and export."""
    dimensions = _load_dimensions(program_id)
    allowed = _faculty_course_ids(program_id)
    allowed_pairs = _faculty_course_campus_pairs(program_id)
    allowed_campuses_by_course = _allowed_campuses_by_course(program_id)
    available_campuses = _available_campuses(program_id)
    if allowed is not None:
        dimensions["courses"] = [
            course for course in dimensions["courses"] if course["id"] in allowed
        ]
    available_course_ids = {course["id"] for course in dimensions["courses"]}
    raw_course_ids = request.args.getlist("course_id")
    try:
        selected_course_ids = {
            parse_int(value, minimum=1) for value in raw_course_ids if value
        }
    except ValueError as error:
        abort(400, str(error))
    if len(selected_course_ids) > 50:
        abort(400, "Select no more than 50 courses per analysis.")
    if not selected_course_ids:
        if request.args.get("course_selection") == "explicit":
            abort(400, "Select at least one course to analyze.")
        selected_course_ids = available_course_ids
    if not selected_course_ids.issubset(available_course_ids):
        abort(403)

    where_parts: list[str] = []
    params: list[int | str] = []
    if selected_course_ids:
        placeholders = ",".join("?" for _ in selected_course_ids)
        where_parts.append(f"ar.course_id IN ({placeholders})")
        params.extend(sorted(selected_course_ids))
    else:
        where_parts.append("1=0")

    selected_dimensions: dict[str, int | None] = {
        "term_id": None,
        "outcome_id": None,
        "indicator_id": None,
    }
    dimension_specs = (
        ("term_id", "academic_terms", "ar.term_id", False),
        ("outcome_id", "outcomes", "ar.outcome_id", False),
        ("indicator_id", "performance_indicators", "ar.indicator_id", True),
    )
    try:
        selected_rows = {}
        for key, table, column, through_outcome in dimension_specs:
            value = request.args.get(key)
            if not value:
                continue
            selected = _scoped_id(
                table, value, program_id, through_outcome=through_outcome
            )
            selected_rows[key] = selected
            selected_dimensions[key] = selected["id"]
            where_parts.append(f"{column}=?")
            params.append(selected["id"])
        if (
            selected_dimensions["outcome_id"]
            and selected_dimensions["indicator_id"]
            and selected_rows["indicator_id"]["outcome_id"]
            != selected_dimensions["outcome_id"]
        ):
            raise ValueError("The selected performance indicator does not belong to the selected outcome.")
    except ValueError as error:
        abort(400, str(error))

    method = request.args.get("method", "")
    if method:
        if method not in {"direct", "indirect"}:
            abort(400, "Unknown assessment method.")
        where_parts.append("ar.method=?")
        params.append(method)

    raw_campuses = [value for value in request.args.getlist("campus") if value]
    if request.args.get("campus_selection") == "explicit" and not raw_campuses:
        abort(400, "Select at least one campus to analyze.")
    selected_campuses: set[str] = set()
    for value in raw_campuses:
        try:
            selected_campuses.add(_assessment_campus(value, required=True))
        except ValueError as error:
            abort(400, str(error))
    if allowed_pairs is not None:
        if not selected_campuses.issubset(set(available_campuses)):
            abort(403)
        if raw_campuses and not any(
            course_id in selected_course_ids and campus in selected_campuses
            for course_id, campus in allowed_pairs
        ):
            abort(403)
    if raw_campuses:
        placeholders = ",".join("?" for _ in selected_campuses)
        where_parts.append(f"ar.campus IN ({placeholders})")
        params.extend(campus for campus in UTRGV_CAMPUSES if campus in selected_campuses)
    else:
        selected_campuses = set(available_campuses)
        if (
            current_app.config.get("EDITION") == "utrgv_mece"
            and not include_unassigned_when_unfiltered
        ):
            placeholders = ",".join("?" for _ in available_campuses)
            if not available_campuses:
                where_parts.append("1=0")
                placeholders = ""
            if placeholders:
                where_parts.append(f"ar.campus IN ({placeholders})")
                params.extend(available_campuses)

    comparison_group = request.args.get("comparison_group", "term")
    if comparison_group not in {"term", "course", "outcome", "indicator"}:
        abort(400, "Unknown campus comparison grouping.")

    evidence_scope = request.args.get("evidence_scope", default_scope)
    if evidence_scope not in {"approved", "all"}:
        abort(400, "Unknown evidence scope.")
    if evidence_scope == "approved":
        where_parts.append("ar.status='approved'")

    return {
        "dimensions": dimensions,
        "selected_course_ids": selected_course_ids,
        "selected_dimensions": selected_dimensions,
        "method": method,
        "evidence_scope": evidence_scope,
        "selected_campuses": selected_campuses,
        "available_campuses": available_campuses,
        "allowed_course_campus_pairs": allowed_pairs,
        "allowed_campuses_by_course": allowed_campuses_by_course,
        "comparison_group": comparison_group,
        "where": "".join(f" AND {part}" for part in where_parts),
        "params": tuple(params),
    }


def _analysis_scope_metrics(records) -> dict:
    rows = list(records)
    count = len(rows)
    values = [float(row["attainment"]) for row in rows]
    met_count = sum(
        float(row["attainment"]) >= float(row["target"]) for row in rows
    )
    return {
        "count": count,
        "average": round(sum(values) / count, 1) if count else None,
        "met_count": met_count,
        "met_rate": round(100.0 * met_count / count, 1) if count else None,
        "courses": len({row["course_id"] for row in rows}),
        "terms": len({row["term_id"] for row in rows}),
        "campuses": len(
            {row["campus"] for row in rows if row["campus"] in UTRGV_CAMPUSES}
        ),
        "unassigned_campus": sum(row["campus"] == "Unassigned" for row in rows),
        **{
            status: sum(row["status"] == status for row in rows)
            for status in ("approved", "draft", "submitted", "returned")
        },
    }


def _scoped_id(table: str, value, program_id: int, *, through_outcome: bool = False):
    item_id = parse_int(value, minimum=1)
    allowed = {"academic_terms", "courses", "outcomes", "rubrics", "performance_indicators"}
    if table not in allowed:
        raise ValueError("Invalid configuration type.")
    if through_outcome:
        row = get_db().execute(
            """SELECT pi.* FROM performance_indicators pi JOIN outcomes o ON o.id = pi.outcome_id
               WHERE pi.id = ? AND o.program_id = ?""",
            (item_id, program_id),
        ).fetchone()
    else:
        row = get_db().execute(f"SELECT * FROM {table} WHERE id = ? AND program_id = ?", (item_id, program_id)).fetchone()
    if not row:
        raise ValueError("A selected item does not belong to this program.")
    return row


@bp.route("/health")
def health():
    get_db().execute("SELECT 1").fetchone()
    return {"status": "ok"}


@bp.route("/setup", methods=["GET", "POST"])
def setup():
    db = get_db()
    if db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
        abort(404)
    if request.method == "POST":
        try:
            setup_token = current_app.config.get("SETUP_TOKEN", "")
            if setup_token and not secrets.compare_digest(request.form.get("setup_token", ""), setup_token):
                raise ValueError("The deployment setup token is not valid.")
            is_utrgv = current_app.config["EDITION"] == "utrgv_mece"
            if is_utrgv:
                from .utrgv_config import ORGANIZATION_NAME, PROGRAM_CODE, PROGRAM_NAME

                institution, program_name, program_code = ORGANIZATION_NAME, PROGRAM_NAME, PROGRAM_CODE
            else:
                institution = request.form.get("institution", "").strip()
                program_name = request.form.get("program_name", "").strip()
                program_code = request.form.get("program_code", "").strip().upper()
            full_name = request.form.get("full_name", "").strip()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            if not all((institution, program_name, program_code, full_name, email)):
                raise ValueError("Complete every setup field.")
            if "@" not in email or len(password) < 12:
                raise ValueError("Use a valid email and a password of at least 12 characters.")
            if is_utrgv:
                from .utrgv_config import OWNER_EMAIL

                if email.casefold() != OWNER_EMAIL.casefold():
                    raise ValueError(
                        "This UTRGV edition can only be initialized by its designated owner."
                    )
            slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in institution).strip("-")
            slug = "-".join(filter(None, slug.split("-"))) or secrets.token_hex(4)
            with db:
                org_id = db.execute(
                    "INSERT INTO organizations(name, slug) VALUES (?, ?)", (institution, slug)
                ).lastrowid
                user_id = db.execute(
                    "INSERT INTO users(email, full_name, password_hash) VALUES (?, ?, ?)",
                    (email, full_name, generate_password_hash(password)),
                ).lastrowid
                db.execute(
                    "INSERT INTO memberships(user_id, organization_id, role) VALUES (?, ?, 'owner')",
                    (user_id, org_id),
                )
                program_id = db.execute(
                    "INSERT INTO programs(organization_id, code, name) VALUES (?, ?, ?)",
                    (org_id, program_code, program_name),
                ).lastrowid
                db.execute(
                    "INSERT INTO program_members(program_id, user_id, access_level) VALUES (?, ?, 'manager')",
                    (program_id, user_id),
                )
                for order, (code, description) in enumerate(STANDARD_OUTCOMES, 1):
                    outcome_id = db.execute(
                        "INSERT INTO outcomes(program_id, code, description, display_order) VALUES (?, ?, ?, ?)",
                        (program_id, code, description, order),
                    ).lastrowid
                    db.execute(
                        "INSERT INTO performance_indicators(outcome_id, code, description, display_order) VALUES (?, 'PI-1', 'Program-defined measurable indicator', 1)",
                        (outcome_id,),
                    )
                rubric_id = db.execute(
                    "INSERT INTO rubrics(program_id, name, description, is_default) VALUES (?, 'EPAN', 'Expert / Practitioner / Apprentice / Novice', 1)",
                    (program_id,),
                ).lastrowid
                for order, (label, score, attained) in enumerate(
                    [("Expert", 4, 1), ("Practitioner", 3, 1), ("Apprentice", 2, 0), ("Novice", 1, 0)], 1
                ):
                    db.execute(
                        "INSERT INTO rubric_levels(rubric_id, label, score, is_attained, display_order) VALUES (?, ?, ?, ?, ?)",
                        (rubric_id, label, score, attained, order),
                    )
                year = date.today().year
                db.execute(
                    "INSERT INTO academic_terms(program_id, name, sort_order) VALUES (?, ?, ?)",
                    (program_id, f"Fall {year}", year * 10 + 2),
                )
                if is_utrgv:
                    from .utrgv_config import seed_utrgv_mece

                    seed_utrgv_mece(db, org_id, program_id)
            if is_utrgv:
                flash(
                    "UTRGV Mechanical Engineering workspace created with the configured catalog and faculty roster. "
                    "Sign in, then verify and activate faculty accounts.",
                    "success",
                )
            else:
                flash("Workspace created. Sign in with the owner account.", "success")
            return redirect(url_for("platform.login"))
        except (ValueError, sqlite3.IntegrityError) as error:
            flash_validation(error)
    designated_owner_email = designated_owner_name = None
    if current_app.config["EDITION"] == "utrgv_mece":
        from .utrgv_config import OWNER_EMAIL, OWNER_NAME

        designated_owner_email = OWNER_EMAIL
        designated_owner_name = OWNER_NAME
    return render_template(
        "setup.html",
        designated_owner_email=designated_owner_email,
        designated_owner_name=designated_owner_name,
    )


@bp.route("/login", methods=["GET", "POST"])
def login():
    if not get_db().execute("SELECT 1 FROM users LIMIT 1").fetchone():
        return redirect(url_for("platform.setup"))
    if request.method == "POST":
        email = (request.form.get("login") or request.form.get("email", "")).strip().lower()
        db = get_db()
        ip_address = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
        failures = db.execute(
            """SELECT COUNT(*) AS n FROM login_attempts
               WHERE email=? AND ip_address=? AND success=0
                 AND attempted_at >= datetime('now','-15 minutes')""",
            (email, ip_address),
        ).fetchone()["n"]
        if failures >= 10:
            flash("Too many attempts. Wait 15 minutes and try again.", "error")
            return render_template("login.html"), 429
        user = db.execute(
            "SELECT * FROM users WHERE (email = ? OR username = ?) AND is_active = 1", (email, email)
        ).fetchone()
        if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
            marked_support = None
            if current_app.config.get("EDITION") == "utrgv_mece":
                marked_support = db.execute(
                    """SELECT psa.program_id,p.organization_id,p.is_active,
                              m.role,pm.access_level
                         FROM program_support_accounts psa
                         JOIN programs p ON p.id=psa.program_id
                         LEFT JOIN memberships m ON m.user_id=psa.user_id
                                                AND m.organization_id=p.organization_id
                         LEFT JOIN program_members pm ON pm.program_id=psa.program_id
                                                     AND pm.user_id=psa.user_id
                        WHERE psa.user_id=?""",
                    (user["id"],),
                ).fetchone()
            support_account = None
            if marked_support:
                if (
                    marked_support["is_active"]
                    and marked_support["role"] == "faculty"
                    and marked_support["access_level"] == "editor"
                ):
                    membership = marked_support
                    program = {"id": marked_support["program_id"]}
                    support_account = _program_support_account(
                        program["id"],
                        membership["organization_id"],
                        user_id=user["id"],
                    )
                else:
                    # A malformed marker always fails closed and can never turn
                    # this dedicated credential into a privileged account.
                    membership = None
                    program = None
            else:
                membership = db.execute(
                    """SELECT * FROM memberships
                       WHERE user_id=? ORDER BY organization_id LIMIT 1""",
                    (user["id"],),
                ).fetchone()
                program = None
                if membership:
                    program = db.execute(
                        """SELECT p.id FROM programs p
                           LEFT JOIN program_members pm
                             ON pm.program_id=p.id AND pm.user_id=?
                           WHERE p.organization_id=? AND p.is_active=1
                             AND (? IN ('owner','admin','coordinator')
                                  OR pm.user_id IS NOT NULL)
                           ORDER BY p.name LIMIT 1""",
                        (
                            user["id"],
                            membership["organization_id"],
                            membership["role"],
                        ),
                    ).fetchone()
                    if (
                        current_app.config.get("EDITION") == "utrgv_mece"
                        and membership["role"] == "faculty"
                    ):
                        roster_account = (
                            program
                            and db.execute(
                                """SELECT 1 FROM faculty_roster fr
                                    JOIN programs p ON p.id=fr.program_id
                                    WHERE fr.program_id=?
                                      AND p.organization_id=?
                                      AND fr.user_id=?
                                      AND fr.status='active'
                                      AND fr.approved_email=? COLLATE NOCASE""",
                                (
                                    program["id"],
                                    membership["organization_id"],
                                    user["id"],
                                    user["email"],
                                ),
                            ).fetchone()
                        )
                        if not roster_account:
                            membership = None
            if membership:
                session.clear()
                session.permanent = True
                session["csrf_token"] = secrets.token_urlsafe(32)
                session["user_id"] = user["id"]
                session["organization_id"] = membership["organization_id"]
                if program:
                    session["program_id"] = program["id"]
                db.execute("UPDATE users SET last_login_at = CURRENT_TIMESTAMP WHERE id = ?", (user["id"],))
                db.execute("DELETE FROM login_attempts WHERE email=? AND ip_address=?", (email, ip_address))
                db.execute("INSERT INTO login_attempts(email,ip_address,success) VALUES (?,?,1)", (email, ip_address))
                db.commit()
                if user["must_change_password"]:
                    return redirect(url_for("platform.change_password"))
                if support_account and not _support_scope_state(
                    program["id"], user["id"]
                )["has_valid_scope"]:
                    # Scope selection is mandatory before a support identity
                    # follows any caller-supplied destination.
                    return redirect(url_for("platform.utrgv_support_scope"))
                return redirect(safe_next_url(request.args.get("next")) or url_for("platform.dashboard"))
        db.execute("INSERT INTO login_attempts(email,ip_address,success) VALUES (?,?,0)", (email, ip_address))
        db.commit()
        flash("Email or password was not recognized.", "error")
    return render_template("login.html")


@bp.get("/forgot-password")
def forgot_password():
    """Give account-recovery guidance without disclosing account existence."""
    return render_template("forgot_password.html")


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("platform.login"))


@bp.route("/account/password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        db = get_db()
        user = db.execute("SELECT password_hash FROM users WHERE id=?", (g.user["id"],)).fetchone()
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        if not check_password_hash(user["password_hash"], current):
            flash("Current password was not recognized.", "error")
        elif len(new) < 12:
            flash("The new password must contain at least 12 characters.", "error")
        elif new != request.form.get("confirm_password"):
            flash("New password entries do not match.", "error")
        else:
            with db:
                db.execute(
                    "UPDATE users SET password_hash=?,must_change_password=0 WHERE id=?",
                    (generate_password_hash(new), g.user["id"]),
                )
                audit("update", "password", g.user["id"])
            session.clear()
            flash("Password changed. Sign in again.", "success")
            return redirect(url_for("platform.login"))
    return render_template("change_password.html")


@bp.post("/program/select")
@login_required
def select_program():
    program = require_program(parse_int(request.form.get("program_id"), minimum=1))
    session["program_id"] = program["id"]
    return redirect(safe_next_url(request.form.get("next")) or url_for("platform.dashboard"))


@bp.route("/")
@login_required
def dashboard():
    program = require_program()
    db = get_db()
    programs = db.execute(
        """SELECT DISTINCT p.* FROM programs p
           LEFT JOIN program_members pm ON pm.program_id = p.id AND pm.user_id = ?
           WHERE p.organization_id = ? AND p.is_active = 1
             AND (? IN ('owner','admin','coordinator') OR pm.user_id IS NOT NULL)
           ORDER BY p.name""",
        (g.user["id"], session["organization_id"], g.membership["role"]),
    ).fetchall()
    records = list(_record_query(program["id"]))
    metrics = summarize_records(records)
    outcome_summary = aggregate(records, "outcome") if records else []
    action_scope, action_scope_params = _faculty_record_scope_sql(
        program["id"], "action_record.course_id", "action_record.campus"
    )
    actions = db.execute(
        f"""SELECT ia.*, o.code AS outcome_code, u.full_name AS owner_name
           FROM improvement_actions ia
           LEFT JOIN outcomes o ON o.id = ia.outcome_id
           LEFT JOIN users u ON u.id = ia.owner_user_id
           LEFT JOIN assessment_records action_record
             ON action_record.id=ia.assessment_id
            AND action_record.program_id=ia.program_id
           WHERE ia.program_id = ? AND ia.status NOT IN ('verified','cancelled')
           {action_scope}
           ORDER BY CASE WHEN ia.due_on IS NULL THEN 1 ELSE 0 END, ia.due_on LIMIT 8""",
        (program["id"], *action_scope_params),
    ).fetchall()
    return render_template(
        "dashboard.html", program=program, programs=programs, metrics=metrics,
        outcome_summary=outcome_summary, recent=records[:8], actions=actions,
    )


@bp.route("/configuration", methods=["GET", "POST"])
@role_required("coordinator")
def configuration():
    program = require_program(edit=True)
    db = get_db()
    if request.method == "POST":
        kind = request.form.get("kind")
        try:
            with db:
                if kind == "program":
                    target = parse_percent(request.form.get("default_target"))
                    db.execute(
                        """UPDATE programs SET name=?, code=?, commission=?, degree_level=?, mission=?,
                           cycle_start=?, cycle_end=?, default_target=? WHERE id=? AND organization_id=?""",
                        (request.form["name"].strip(), request.form["code"].strip().upper(),
                         request.form["commission"].strip(), request.form["degree_level"].strip(),
                         request.form.get("mission", "").strip(), request.form.get("cycle_start") or None,
                         request.form.get("cycle_end") or None, target, program["id"], session["organization_id"]),
                    )
                    audit("update", "program", program["id"])
                elif kind == "course":
                    cursor = db.execute(
                        "INSERT INTO courses(program_id, code, name, description) VALUES (?, ?, ?, ?)",
                        (program["id"], request.form["code"].strip().upper(), request.form["name"].strip(), request.form.get("description", "").strip()),
                    )
                    audit("create", "course", cursor.lastrowid)
                elif kind == "term":
                    cursor = db.execute(
                        "INSERT INTO academic_terms(program_id, name, starts_on, ends_on, sort_order) VALUES (?, ?, ?, ?, ?)",
                        (program["id"], request.form["name"].strip(), request.form.get("starts_on") or None,
                         request.form.get("ends_on") or None, parse_int(request.form.get("sort_order") or 0)),
                    )
                    audit("create", "term", cursor.lastrowid)
                elif kind == "outcome":
                    cursor = db.execute(
                        "INSERT INTO outcomes(program_id, code, description, display_order, target) VALUES (?, ?, ?, ?, ?)",
                        (program["id"], request.form["code"].strip(), request.form["description"].strip(),
                         parse_int(request.form.get("display_order") or 0),
                         parse_percent(request.form["target"]) if request.form.get("target") else None),
                    )
                    audit("create", "outcome", cursor.lastrowid)
                elif kind == "indicator":
                    outcome = _scoped_id("outcomes", request.form.get("outcome_id"), program["id"])
                    cursor = db.execute(
                        "INSERT INTO performance_indicators(outcome_id, code, description, display_order, target) VALUES (?, ?, ?, ?, ?)",
                        (outcome["id"], request.form["code"].strip(), request.form["description"].strip(),
                         parse_int(request.form.get("display_order") or 0),
                         parse_percent(request.form["target"]) if request.form.get("target") else None),
                    )
                    audit("create", "indicator", cursor.lastrowid)
                elif kind == "rubric":
                    name = request.form["name"].strip()
                    levels = []
                    for line in request.form.get("levels", "").splitlines():
                        parts = [part.strip() for part in line.split("|")]
                        if len(parts) != 3:
                            raise ValueError("Each rubric level must use Label | Score | attained yes/no.")
                        levels.append((parts[0], float(parts[1]), 1 if parts[2].lower() in {"yes", "y", "true", "1"} else 0))
                    if len(levels) < 2:
                        raise ValueError("A rubric needs at least two levels.")
                    rubric_id = db.execute(
                        "INSERT INTO rubrics(program_id, name, description) VALUES (?, ?, ?)",
                        (program["id"], name, request.form.get("description", "").strip()),
                    ).lastrowid
                    for order, (label, score, attained) in enumerate(levels, 1):
                        db.execute(
                            "INSERT INTO rubric_levels(rubric_id, label, score, is_attained, display_order) VALUES (?, ?, ?, ?, ?)",
                            (rubric_id, label, score, attained, order),
                        )
                    audit("create", "rubric", rubric_id)
                else:
                    raise ValueError("Unknown configuration item.")
            flash("Configuration saved.", "success")
            return redirect(url_for("platform.configuration"))
        except (ValueError, KeyError, sqlite3.IntegrityError) as error:
            flash_validation(error)
    dimensions = _load_dimensions(program["id"])
    dimensions["levels"] = db.execute(
        """SELECT rl.*, r.name AS rubric_name FROM rubric_levels rl JOIN rubrics r ON r.id=rl.rubric_id
           WHERE r.program_id=? ORDER BY r.name, rl.display_order""", (program["id"],)
    ).fetchall()
    return render_template("configuration.html", program=program, **dimensions)


@bp.route("/assessments")
@login_required
def assessments():
    program = require_program()
    where, params = "", []
    for key, column in (("status", "ar.status"), ("term_id", "ar.term_id"), ("course_id", "ar.course_id"), ("outcome_id", "ar.outcome_id")):
        value = request.args.get(key)
        if value:
            where += f" AND {column} = ?"
            params.append(value)
    campus = request.args.get("campus", "")
    if campus:
        try:
            campus = _assessment_campus(campus, required=True)
        except ValueError as error:
            abort(400, str(error))
        if (
            _faculty_course_campus_pairs(program["id"]) is not None
            and campus not in _available_campuses(program["id"])
        ):
            abort(403)
        where += " AND ar.campus = ?"
        params.append(campus)
    records = list(_record_query(program["id"], where, tuple(params)))
    allowed = _faculty_course_ids(program["id"])
    dimensions = _load_dimensions(program["id"])
    if allowed is not None:
        dimensions["courses"] = [
            course for course in dimensions["courses"] if course["id"] in allowed
        ]
    return render_template(
        "assessments.html",
        program=program,
        records=records,
        campuses=_available_campuses(program["id"]),
        allowed_campuses_by_course=_allowed_campuses_by_course(program["id"]),
        **dimensions,
    )


@bp.route("/assessments/new", methods=["GET", "POST"])
@login_required
def assessment_new():
    return _assessment_form(None)


@bp.route("/assessments/<int:record_id>/edit", methods=["GET", "POST"])
@login_required
def assessment_edit(record_id: int):
    return _assessment_form(record_id)


def _assessment_form(record_id: int | None):
    program = require_program(edit=record_id is None or request.method == "POST")
    db = get_db()
    percentage_entry = current_app.config["EDITION"] == "utrgv_mece"
    record = None
    legacy_source = None
    if record_id:
        record = db.execute(
            "SELECT * FROM assessment_records WHERE id=? AND program_id=?", (record_id, program["id"])
        ).fetchone()
        if not record:
            abort(404)
        _require_current_record_access(
            program["id"], record["course_id"], record["campus"]
        )
        legacy_source = db.execute(
            "SELECT * FROM legacy_import_items WHERE assessment_id=? AND program_id=?",
            (record_id, program["id"]),
        ).fetchone()
    is_admin_editor = g.membership["role"] in ADMIN_EDIT_ROLES
    can_edit = (
        g.membership["role"] != "reviewer"
        and (record is None or g.membership["role"] in MANAGER_ROLES or record["collected_by"] == g.user["id"])
        and (record is None or record["status"] != "approved" or g.membership["role"] in MANAGER_ROLES)
        and (legacy_source is None or is_admin_editor)
    )
    if request.method == "POST" and not can_edit:
        abort(403)
    dimensions = _load_dimensions(program["id"])
    assigned = _faculty_course_ids(program["id"])
    assigned_pairs = _faculty_course_campus_pairs(program["id"])
    allowed_campuses_by_course = _allowed_campuses_by_course(program["id"])
    if assigned is not None:
        dimensions["courses"] = [course for course in dimensions["courses"] if course["id"] in assigned]
    if request.method == "POST":
        try:
            term = _scoped_id("academic_terms", request.form.get("term_id"), program["id"])
            course = _scoped_id("courses", request.form.get("course_id"), program["id"])
            outcome = _scoped_id("outcomes", request.form.get("outcome_id"), program["id"])
            indicator = _scoped_id("performance_indicators", request.form.get("indicator_id"), program["id"], through_outcome=True)
            rubric = _scoped_id(
                "rubrics",
                record["rubric_id"] if legacy_source else request.form.get("rubric_id"),
                program["id"],
            )
            if indicator["outcome_id"] != outcome["id"]:
                raise ValueError("The performance indicator must belong to the selected outcome.")
            if assigned is not None and course["id"] not in assigned:
                abort(403)
            submitted_record_version = (
                parse_int(request.form.get("record_version"), minimum=1)
                if record else None
            )
            target = parse_percent(request.form.get("target"))
            campus = _assessment_campus(
                request.form.get("campus"),
                required=current_app.config["EDITION"] == "utrgv_mece",
            )
            _require_current_record_access(program["id"], course["id"], campus)
            levels = db.execute(
                "SELECT * FROM rubric_levels WHERE rubric_id=? ORDER BY display_order", (rubric["id"],)
            ).fetchall()
            percentages = None
            if percentage_entry or legacy_source:
                if legacy_source and not is_admin_editor:
                    abort(403)
                if rubric["name"].casefold() != "epan":
                    raise ValueError("UTRGV assessment records require the EPAN rubric.")
                percentages = _utrgv_epan_percentages(request.form, levels)
                from .legacy_import import _scaled_counts

                sample_size = None
                result_basis = "percentages"
                result_rows = [
                    (level["id"], count, percent)
                    for level, count, percent in zip(
                        levels,
                        _scaled_counts(percentages),
                        percentages,
                        strict=True,
                    )
                ]
            else:
                sample_size = parse_int(request.form.get("sample_size"), minimum=1)
                counts = [
                    (
                        level["id"],
                        parse_int(
                            request.form.get(f"level_{level['id']}", 0),
                            minimum=0,
                        ),
                    )
                    for level in levels
                ]
                if sum(count for _, count in counts) != sample_size:
                    raise ValueError("Rubric counts must add up exactly to the sample size.")
                result_basis = "student_counts"
                result_rows = [
                    (level_id, count, None) for level_id, count in counts
                ]
            method = str(request.form.get("method") or "").strip().lower()
            if method not in {"direct", "indirect"}:
                raise ValueError("Select a valid assessment method.")
            assessment_tool = _required_text(
                request.form.get("assessment_tool"), "Assessment tool"
            )
            bloom_level = str(request.form.get("bloom_level") or "").strip()
            rationale = str(request.form.get("rationale") or "").strip()
            observations = str(request.form.get("observations") or "").strip()
            action_notes = str(request.form.get("action_notes") or "").strip()
            if percentage_entry:
                bloom_level = _required_text(bloom_level, "Bloom level")
                rationale = _required_text(rationale, "Assessment rationale")
                observations = _required_text(observations, "Observations")
                action_notes = _required_text(
                    action_notes, "Improvement/action notes"
                )
            values = (
                term["id"], course["id"], outcome["id"], indicator["id"], rubric["id"], campus,
                method, assessment_tool, bloom_level, sample_size, result_basis, target,
                rationale, observations, action_notes,
            )
            before_snapshot = None
            admin_change_note = ""
            requested_admin_reason = ""
            if record and is_admin_editor:
                before_snapshot = {
                    key: record[key]
                    for key in (
                        "term_id", "course_id", "outcome_id", "indicator_id",
                        "rubric_id", "campus", "method", "assessment_tool",
                        "bloom_level", "sample_size", "result_basis", "target", "rationale",
                        "observations", "action_notes", "status",
                    )
                }
                if legacy_source:
                    before_snapshot["source_percentages"] = {
                        label: legacy_source[f"{label}_percent"]
                        for label in ("expert", "practitioner", "apprentice", "novice")
                    }
                elif record["result_basis"] == "percentages":
                    before_snapshot["rubric_percentages"] = {
                        row["label"]: row["level_percent"]
                        for row in db.execute(
                            """SELECT rl.label,rs.level_percent
                                 FROM assessment_results rs
                                 JOIN rubric_levels rl ON rl.id=rs.rubric_level_id
                                 JOIN rubrics r ON r.id=rl.rubric_id
                                WHERE rs.assessment_id=? AND r.program_id=?
                                ORDER BY rl.display_order,rl.id""",
                            (record["id"], program["id"]),
                        )
                    }
                else:
                    before_snapshot["rubric_counts"] = {
                        row["label"]: row["student_count"]
                        for row in db.execute(
                            """SELECT rl.label,rs.student_count
                                 FROM assessment_results rs
                                 JOIN rubric_levels rl ON rl.id=rs.rubric_level_id
                                 JOIN rubrics r ON r.id=rl.rubric_id
                                WHERE rs.assessment_id=? AND r.program_id=?
                                ORDER BY rl.display_order,rl.id""",
                            (record["id"], program["id"]),
                        )
                    }
                requested_admin_reason = request.form.get(
                    "admin_change_note", ""
                ).strip()
                if percentage_entry and not requested_admin_reason:
                    raise ValueError("Reason for administrative change is required.")
                admin_change_note = requested_admin_reason or "Administrative correction."
            with db:
                # An owner may narrow a faculty invitation while an older form
                # remains open.  Re-check the submitted exact pair inside the
                # write transaction before inserting or moving a record.
                _require_current_record_access(program["id"], course["id"], campus)
                if record:
                    updated = db.execute(
                        """UPDATE assessment_records SET term_id=?,course_id=?,outcome_id=?,indicator_id=?,rubric_id=?,
                           campus=?,method=?,assessment_tool=?,bloom_level=?,sample_size=?,result_basis=?,target=?,rationale=?,observations=?,
                           action_notes=?,status='draft',submitted_at=NULL,approved_at=NULL,approved_by=NULL,
                           record_version=record_version+1,updated_at=CURRENT_TIMESTAMP
                           WHERE id=? AND program_id=? AND record_version=?""",
                        (
                            *values, record["id"], program["id"],
                            submitted_record_version,
                        ),
                    )
                    if updated.rowcount != 1:
                        abort(
                            409,
                            "This assessment changed while you were editing it. "
                            "Refresh and try again.",
                        )
                    assessment_id = record["id"]
                    db.execute("DELETE FROM assessment_results WHERE assessment_id=?", (assessment_id,))
                    if legacy_source and percentages is not None:
                        db.execute(
                            """UPDATE legacy_import_items
                               SET expert_percent=?,practitioner_percent=?,
                                   apprentice_percent=?,novice_percent=?
                               WHERE id=? AND assessment_id=? AND program_id=?""",
                            (
                                *percentages,
                                legacy_source["id"], assessment_id, program["id"],
                            ),
                        )
                    action = "update"
                else:
                    assessment_id = db.execute(
                        """INSERT INTO assessment_records
                           (program_id,term_id,course_id,outcome_id,indicator_id,rubric_id,collected_by,method,
                            assessment_tool,bloom_level,sample_size,result_basis,target,rationale,observations,action_notes,campus)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (program["id"], *values[:5], g.user["id"], *values[6:], values[5]),
                    ).lastrowid
                    action = "create"
                db.executemany(
                    """INSERT INTO assessment_results
                       (assessment_id,rubric_level_id,student_count,level_percent)
                       VALUES (?,?,?,?)""",
                    [
                        (assessment_id, level_id, count, percent)
                        for level_id, count, percent in result_rows
                    ],
                )
                if record and is_admin_editor and before_snapshot is not None:
                    after_snapshot = {
                        "term_id": term["id"],
                        "course_id": course["id"],
                        "outcome_id": outcome["id"],
                        "indicator_id": indicator["id"],
                        "rubric_id": rubric["id"],
                        "campus": campus,
                        "method": values[6],
                        "assessment_tool": values[7],
                        "bloom_level": values[8],
                        "sample_size": sample_size,
                        "result_basis": result_basis,
                        "target": target,
                        "rationale": values[12],
                        "observations": values[13],
                        "action_notes": values[14],
                        "status": "draft",
                    }
                    if percentages is not None:
                        percentage_key = (
                            "source_percentages" if legacy_source
                            else "rubric_percentages"
                        )
                        after_snapshot[percentage_key] = dict(
                            zip(
                                ("expert", "practitioner", "apprentice", "novice"),
                                percentages,
                                strict=True,
                            )
                        )
                    else:
                        after_snapshot["rubric_counts"] = {
                            level["label"]: count
                            for level, (_level_id, count, _percent) in zip(
                                levels, result_rows, strict=True
                            )
                        }
                    db.execute(
                        """INSERT INTO assessment_revisions
                           (program_id,assessment_id,changed_by,changed_by_name,
                            change_note,before_json,after_json)
                           VALUES (?,?,?,?,?,?,?)""",
                        (
                            program["id"], assessment_id, g.user["id"],
                            g.user["full_name"], admin_change_note,
                            json.dumps(before_snapshot, sort_keys=True, separators=(",", ":")),
                            json.dumps(after_snapshot, sort_keys=True, separators=(",", ":")),
                        ),
                    )
                audit(
                    action,
                    "assessment",
                    assessment_id,
                    {
                        "previous_status": record["status"] if record else None,
                        "new_status": "draft",
                        "review_reset": bool(
                            record and record["status"] in {"submitted", "approved"}
                        ),
                        "administrative_change": bool(record and is_admin_editor),
                        "change_note": admin_change_note or None,
                        "reason": requested_admin_reason or None,
                    },
                )
            if record and is_admin_editor:
                flash(
                    "Administrative changes saved as a draft. A permanent change note "
                    "was added to this assessment.",
                    "success",
                )
            elif record and record["status"] in {"submitted", "approved"}:
                flash(
                    "Assessment changes saved as a draft. The prior review was cleared; "
                    "submit the record again after checking the changes.",
                    "success",
                )
            else:
                flash("Assessment saved as a draft.", "success")
            return redirect(url_for("platform.assessment_edit", record_id=assessment_id))
        except (ValueError, sqlite3.IntegrityError) as error:
            flash_validation(error)
    levels = db.execute(
        """SELECT rl.*, r.name AS rubric_name,
                  COALESCE(rs.student_count,0) AS student_count,rs.level_percent
           FROM rubric_levels rl JOIN rubrics r ON r.id=rl.rubric_id
           LEFT JOIN assessment_results rs ON rs.rubric_level_id=rl.id AND rs.assessment_id=?
           WHERE r.program_id=? ORDER BY r.name, rl.display_order""",
        (record_id or -1, program["id"]),
    ).fetchall()
    evidence = db.execute(
        """SELECT e.*
             FROM evidence_items e
             JOIN assessment_records ar
               ON ar.id=e.assessment_id AND ar.program_id=e.program_id
            WHERE e.assessment_id=? AND e.program_id=? AND e.organization_id=?
            ORDER BY e.created_at DESC""",
        (record_id or -1, program["id"], session["organization_id"]),
    ).fetchall()
    revisions = db.execute(
        """SELECT * FROM assessment_revisions
           WHERE assessment_id=? AND program_id=?
           ORDER BY created_at DESC,id DESC""",
        (record_id or -1, program["id"]),
    ).fetchall()
    campus_is_reviewable = (
        current_app.config["EDITION"] != "utrgv_mece"
        or (record is not None and record["campus"] in UTRGV_CAMPUSES)
    )
    can_submit = bool(
        record
        and record["status"] in {"draft", "returned"}
        and can_edit
        and campus_is_reviewable
        and (
            g.membership["role"] in MANAGER_ROLES
            or record["collected_by"] == g.user["id"]
        )
    )
    can_attach_evidence = bool(record and can_edit)
    will_reset_review = bool(
        record and record["status"] in {"submitted", "approved"} and can_edit
    )
    can_return = bool(
        record
        and record["status"] == "submitted"
        and g.membership["role"] in MANAGER_ROLES
    )
    can_approve = can_return and campus_is_reviewable
    return render_template(
        "assessment_form.html", program=program, record=record, levels=levels,
        evidence=evidence, can_edit=can_edit, can_submit=can_submit,
        can_attach_evidence=can_attach_evidence, can_return=can_return,
        can_approve=can_approve,
        will_reset_review=will_reset_review, legacy_source=legacy_source,
        is_admin_editor=is_admin_editor, revisions=revisions,
        campuses=_available_campuses(program["id"]),
        allowed_course_campus_pairs=assigned_pairs,
        allowed_campuses_by_course=allowed_campuses_by_course,
        percentage_entry=percentage_entry, **dimensions,
    )


@bp.post("/assessments/<int:record_id>/status")
@login_required
def assessment_status(record_id: int):
    program = require_program(edit=True)
    db = get_db()
    record = db.execute("SELECT * FROM assessment_records WHERE id=? AND program_id=?", (record_id, program["id"])).fetchone()
    if not record:
        abort(404)
    _require_current_record_access(
        program["id"], record["course_id"], record["campus"]
    )
    action = request.form.get("action")
    transitions = {"submit": ({"draft", "returned"}, "submitted"), "approve": ({"submitted"}, "approved"), "return": ({"submitted"}, "returned")}
    if action not in transitions or record["status"] not in transitions[action][0]:
        abort(400, "That workflow transition is not available.")
    if action in {"approve", "return"} and g.membership["role"] not in MANAGER_ROLES:
        abort(403)
    if action == "submit" and record["collected_by"] != g.user["id"] and g.membership["role"] not in MANAGER_ROLES:
        abort(403)
    if (
        current_app.config.get("EDITION") == "utrgv_mece"
        and action in {"submit", "approve"}
    ):
        try:
            _validate_utrgv_record_for_review(record_id, program["id"])
        except ValueError as error:
            abort(400, str(error))
    new_status = transitions[action][1]
    with db:
        # Exact course-campus access can be revoked while a stale form is open.
        # Check it again inside the write transaction before changing workflow.
        _require_current_record_access(
            program["id"], record["course_id"], record["campus"]
        )
        updated = db.execute(
            """UPDATE assessment_records SET status=?, submitted_at=CASE WHEN ?='submitted' THEN CURRENT_TIMESTAMP ELSE submitted_at END,
               approved_at=CASE WHEN ?='approved' THEN CURRENT_TIMESTAMP ELSE NULL END,
               approved_by=CASE WHEN ?='approved' THEN ? ELSE NULL END,
               record_version=record_version+1,updated_at=CURRENT_TIMESTAMP
               WHERE id=? AND program_id=? AND status=? AND record_version=?""",
            (
                new_status, new_status, new_status, new_status, g.user["id"],
                record_id, program["id"], record["status"], record["record_version"],
            ),
        )
        if updated.rowcount != 1:
            abort(400, "This record changed while you were reviewing it. Refresh and try again.")
        audit(action, "assessment", record_id, {"from": record["status"], "to": new_status})
    flash(f"Assessment marked {new_status}.", "success")
    return redirect(url_for("platform.assessment_edit", record_id=record_id))


def _bulk_approval_ids(field: str, *, limit: int) -> list[int]:
    """Parse one repeated bulk-selection field without accepting ambiguous values."""
    raw_values = request.form.getlist(field)
    try:
        values = sorted({parse_int(value, minimum=1) for value in raw_values if value})
    except ValueError as error:
        abort(400, str(error))
    if len(values) > limit:
        abort(400, f"Select no more than {limit} items at one time.")
    return values


def _bulk_approval_filters(program_id: int) -> tuple[list[str], list[int | str], dict]:
    """Return validated assessment-list filters for an approval batch."""
    clauses: list[str] = []
    params: list[int | str] = []
    filters: dict[str, int | str] = {}

    status = request.form.get("filter_status", "").strip().lower()
    if status:
        if status not in {"draft", "submitted", "approved", "returned"}:
            abort(400, "Unknown assessment status filter.")
        clauses.append("ar.status=?")
        params.append(status)
        filters["status"] = status

    for field, column, table in (
        ("filter_term_id", "ar.term_id", "academic_terms"),
        ("filter_course_id", "ar.course_id", "courses"),
        ("filter_outcome_id", "ar.outcome_id", "outcomes"),
    ):
        raw_value = request.form.get(field, "").strip()
        if not raw_value:
            continue
        try:
            item = _scoped_id(table, raw_value, program_id)
        except ValueError as error:
            abort(400, str(error))
        clauses.append(f"{column}=?")
        params.append(item["id"])
        filters[field.removeprefix("filter_")] = item["id"]

    raw_campus = request.form.get("filter_campus", "").strip()
    if raw_campus:
        try:
            campus = _assessment_campus(raw_campus, required=True)
        except ValueError as error:
            abort(400, str(error))
        clauses.append("ar.campus=?")
        params.append(campus)
        filters["campus"] = campus

    return clauses, params, filters


@bp.post("/assessments/bulk-approve")
@role_required("admin")
def bulk_approve_assessments():
    """Atomically approve selected UTRGV draft/submitted assessment records."""
    if current_app.config.get("EDITION") != "utrgv_mece":
        abort(404)

    program = require_program(edit=True)
    db = get_db()
    selection_mode = request.form.get("selection_mode", "").strip().lower()
    if selection_mode not in {"records", "courses", "all"}:
        abort(400, "Choose records, courses, or all matching records to approve.")

    clauses, params, visible_filters = _bulk_approval_filters(program["id"])
    record_ids = _bulk_approval_ids("record_ids", limit=500)
    course_ids = _bulk_approval_ids("course_ids", limit=100)

    if selection_mode == "records":
        if not record_ids:
            abort(400, "Select at least one assessment record to approve.")
        placeholders = ",".join("?" for _ in record_ids)
        clauses.append(f"ar.id IN ({placeholders})")
        params.extend(record_ids)
    elif selection_mode == "courses":
        if not course_ids:
            abort(400, "Select at least one course to approve.")
        placeholders = ",".join("?" for _ in course_ids)
        scoped_courses = db.execute(
            f"SELECT id FROM courses WHERE program_id=? AND id IN ({placeholders})",
            (program["id"], *course_ids),
        ).fetchall()
        if len(scoped_courses) != len(course_ids):
            abort(403)
        clauses.append(f"ar.course_id IN ({placeholders})")
        params.extend(course_ids)
    if selection_mode in {"courses", "all"}:
        clauses.append("ar.status IN ('draft','submitted')")

    where = " AND ".join(clauses)
    if where:
        where = " AND " + where
    candidates = db.execute(
        f"""SELECT ar.id,ar.course_id,ar.status,ar.record_version
              FROM assessment_records ar
              JOIN academic_terms t
                ON t.id=ar.term_id AND t.program_id=ar.program_id
              JOIN courses c
                ON c.id=ar.course_id AND c.program_id=ar.program_id
              JOIN outcomes o
                ON o.id=ar.outcome_id AND o.program_id=ar.program_id
              JOIN performance_indicators pi
                ON pi.id=ar.indicator_id AND pi.outcome_id=ar.outcome_id
              JOIN rubrics r
                ON r.id=ar.rubric_id AND r.program_id=ar.program_id
             WHERE ar.program_id=?{where}
             ORDER BY ar.id
             LIMIT ?""",
        (program["id"], *params, MAX_BULK_APPROVAL_RECORDS + 1),
    ).fetchall()

    if len(candidates) > MAX_BULK_APPROVAL_RECORDS:
        abort(
            400,
            f"This selection contains more than {MAX_BULK_APPROVAL_RECORDS} eligible "
            "records. Narrow the filters and approve them in smaller batches.",
        )

    if selection_mode == "records":
        # Explicit row selection is strict: a stale, ineligible, or foreign row
        # must never turn a request into an unintended partial approval.
        found_ids = {row["id"] for row in candidates}
        if found_ids != set(record_ids):
            abort(403)
        ineligible = [row["id"] for row in candidates if row["status"] not in {"draft", "submitted"}]
        if ineligible:
            abort(400, "Only draft or submitted assessment records can be bulk approved.")
    # Course and all-visible selection intentionally leave approved and
    # returned records unchanged through their eligibility predicate above.

    redirect_filters = {
        key: request.form.get(f"filter_{key}", "").strip()
        for key in ("status", "term_id", "course_id", "outcome_id", "campus")
        if request.form.get(f"filter_{key}", "").strip()
    }
    redirect_url = url_for("platform.assessments", **redirect_filters)
    if not candidates:
        flash("No draft or submitted records matched this selection.", "warning")
        return redirect(redirect_url)

    validation_errors = []
    for row in candidates:
        try:
            _validate_utrgv_record_for_review(row["id"], program["id"])
        except ValueError as error:
            validation_errors.append(f"Record {row['id']}: {error}")
    if validation_errors:
        preview = "; ".join(validation_errors[:5])
        remaining = len(validation_errors) - 5
        if remaining:
            preview += f"; and {remaining} more incomplete record(s)"
        abort(400, "No records were approved. " + preview)

    batch_id = secrets.token_urlsafe(12)
    status_counts = {
        status: sum(row["status"] == status for row in candidates)
        for status in ("draft", "submitted")
    }
    with db:
        for row in candidates:
            updated = db.execute(
                """UPDATE assessment_records
                      SET status='approved',
                          submitted_at=COALESCE(submitted_at,CURRENT_TIMESTAMP),
                          approved_at=CURRENT_TIMESTAMP,approved_by=?,
                          record_version=record_version+1,
                          updated_at=CURRENT_TIMESTAMP
                    WHERE id=? AND program_id=? AND status=? AND record_version=?
                      AND status IN ('draft','submitted')""",
                (
                    g.user["id"], row["id"], program["id"], row["status"],
                    row["record_version"],
                ),
            )
            if updated.rowcount != 1:
                abort(
                    409,
                    "A selected record changed during approval. No records were approved; "
                    "refresh the list and try again.",
                )
            audit(
                "approve",
                "assessment",
                row["id"],
                {
                    "from": row["status"],
                    "to": "approved",
                    "bulk": True,
                    "batch_id": batch_id,
                    "selection_mode": selection_mode,
                },
            )
        audit(
            "bulk_approve",
            "assessment_batch",
            batch_id,
            {
                "selection_mode": selection_mode,
                "record_count": len(candidates),
                "record_ids": [row["id"] for row in candidates],
                "course_ids": course_ids,
                "filters": visible_filters,
                "from_status_counts": status_counts,
            },
        )

    flash(
        f"Approved {len(candidates)} assessment record(s): "
        f"{status_counts['draft']} draft and {status_counts['submitted']} submitted.",
        "success",
    )
    return redirect(redirect_url)


@bp.post("/assessments/<int:record_id>/evidence")
@login_required
def evidence_add(record_id: int):
    program = require_program(edit=True)
    db = get_db()
    record = db.execute("SELECT * FROM assessment_records WHERE id=? AND program_id=?", (record_id, program["id"])).fetchone()
    if not record:
        abort(404)
    _require_current_record_access(
        program["id"], record["course_id"], record["campus"]
    )
    legacy_source = db.execute(
        "SELECT 1 FROM legacy_import_items WHERE assessment_id=? AND program_id=?",
        (record_id, program["id"]),
    ).fetchone()
    if legacy_source and g.membership["role"] not in ADMIN_EDIT_ROLES:
        abort(403)
    if g.membership["role"] not in MANAGER_ROLES and (
        record["collected_by"] != g.user["id"]
        or record["status"] not in {"draft", "returned", "submitted"}
    ):
        abort(403)
    title = request.form.get("title", "").strip()
    source_url = request.form.get("source_url", "").strip() or None
    upload = request.files.get("file")
    storage_key = original = mime = None
    destination = None
    if not title:
        abort(400, "Provide an evidence title.")
    if source_url and urlparse(source_url).scheme not in {"http", "https"}:
        abort(400, "Evidence links must use HTTP or HTTPS.")
    if upload and upload.filename:
        original = secure_filename(upload.filename)
        extension = Path(original).suffix.lower()
        if extension not in ALLOWED_UPLOADS:
            abort(400, "This file type is not allowed.")
        storage_key = f"{session['organization_id']}/{program['id']}/{secrets.token_hex(16)}{extension}"
        target = Path(os.fspath(current_app.config["UPLOAD_FOLDER"]))
        destination = target / storage_key
        mime = upload.mimetype or mimetypes.guess_type(original)[0]
    if not source_url and not storage_key:
        abort(400, "Provide either a link or a file.")
    review_reset = record["status"] in {"submitted", "approved"}
    with db:
        # Authorization is mutable; re-check it immediately before persisting
        # evidence so a revoked assignment cannot be reused from an old page.
        _require_current_record_access(
            program["id"], record["course_id"], record["campus"]
        )
        if review_reset:
            updated = db.execute(
                """UPDATE assessment_records
                   SET status='draft',submitted_at=NULL,approved_at=NULL,
                       approved_by=NULL,record_version=record_version+1,
                       updated_at=CURRENT_TIMESTAMP
                   WHERE id=? AND program_id=? AND record_version=?""",
                (record_id, program["id"], record["record_version"]),
            )
        else:
            updated = db.execute(
                """UPDATE assessment_records
                   SET record_version=record_version+1,updated_at=CURRENT_TIMESTAMP
                   WHERE id=? AND program_id=? AND record_version=?""",
                (record_id, program["id"], record["record_version"]),
            )
        if updated.rowcount != 1:
            abort(
                409,
                "This assessment changed while you were adding evidence. "
                "Refresh and try again.",
            )
        if destination is not None:
            destination.parent.mkdir(parents=True, exist_ok=True)
            upload.save(destination)
        evidence_id = db.execute(
            """INSERT INTO evidence_items
               (organization_id,program_id,assessment_id,title,description,evidence_type,source_url,storage_key,
                original_filename,mime_type,uploaded_by) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (session["organization_id"], program["id"], record_id, title, request.form.get("description", "").strip(),
             request.form.get("evidence_type", "other"), source_url, storage_key, original, mime, g.user["id"]),
        ).lastrowid
        audit(
            "create",
            "evidence",
            evidence_id,
            {
                "assessment_id": record_id,
                "previous_status": record["status"],
                "new_status": "draft" if review_reset else record["status"],
                "review_reset": review_reset,
            },
        )
    if review_reset:
        flash(
            "Evidence attached and the record returned to draft. The prior review was "
            "cleared; submit it again after checking the new evidence.",
            "success",
        )
    else:
        flash("Evidence attached.", "success")
    return redirect(url_for("platform.assessment_edit", record_id=record_id))


@bp.get("/evidence/<int:evidence_id>/download")
@login_required
def evidence_download(evidence_id: int):
    program = require_program()
    item = get_db().execute(
        """SELECT e.*,ar.course_id,ar.campus FROM evidence_items e
           JOIN assessment_records ar
             ON ar.id=e.assessment_id AND ar.program_id=e.program_id
           WHERE e.id=? AND e.organization_id=? AND e.program_id=?""",
        (evidence_id, session["organization_id"], program["id"]),
    ).fetchone()
    if not item or not item["storage_key"]:
        abort(404)
    _require_current_record_access(
        program["id"], item["course_id"], item["campus"]
    )
    path = Path(current_app.config["UPLOAD_FOLDER"]) / item["storage_key"]
    return send_from_directory(path.parent, path.name, as_attachment=True, download_name=item["original_filename"])


@bp.route("/actions", methods=["GET", "POST"])
@login_required
def actions():
    program = require_program(edit=request.method == "POST")
    db = get_db()
    if request.method == "POST":
        if g.membership["role"] in {"faculty", "reviewer"}:
            abort(403)
        try:
            title = request.form.get("title", "").strip()
            description = request.form.get("description", "").strip()
            if not title or not description:
                raise ValueError("Action title and description are required.")
            outcome_id = None
            if request.form.get("outcome_id"):
                outcome_id = _scoped_id("outcomes", request.form["outcome_id"], program["id"])["id"]
            owner_user_id = request.form.get("owner_user_id") or None
            if owner_user_id:
                owner = db.execute(
                    """SELECT u.id FROM users u JOIN memberships m ON m.user_id=u.id
                       WHERE u.id=? AND m.organization_id=? AND u.is_active=1""",
                    (owner_user_id, session["organization_id"]),
                ).fetchone()
                if not owner:
                    raise ValueError("The selected action owner is not an active member of this institution.")
                owner_user_id = owner["id"]
            with db:
                action_id = db.execute(
                    """INSERT INTO improvement_actions
                       (program_id,outcome_id,title,description,owner_user_id,due_on,status,created_by)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (program["id"], outcome_id, title, description, owner_user_id,
                     request.form.get("due_on") or None, request.form.get("status", "planned"), g.user["id"]),
                ).lastrowid
                audit("create", "improvement_action", action_id)
            flash("Improvement action created.", "success")
            return redirect(url_for("platform.actions"))
        except (ValueError, sqlite3.IntegrityError) as error:
            flash_validation(error)
    action_scope, action_scope_params = _faculty_record_scope_sql(
        program["id"], "action_record.course_id", "action_record.campus"
    )
    rows = db.execute(
        f"""SELECT ia.*, o.code AS outcome_code, u.full_name AS owner_name
           FROM improvement_actions ia LEFT JOIN outcomes o ON o.id=ia.outcome_id
           LEFT JOIN users u ON u.id=ia.owner_user_id
           LEFT JOIN assessment_records action_record
             ON action_record.id=ia.assessment_id
            AND action_record.program_id=ia.program_id
           WHERE ia.program_id=?{action_scope}
           ORDER BY CASE ia.status WHEN 'in_progress' THEN 1 WHEN 'planned' THEN 2 ELSE 3 END, ia.due_on""",
        (program["id"], *action_scope_params),
    ).fetchall()
    if g.membership["role"] in MANAGER_ROLES:
        members = db.execute(
            """SELECT u.id,u.full_name FROM users u JOIN memberships m ON m.user_id=u.id
               WHERE m.organization_id=? AND u.is_active=1 ORDER BY u.full_name""",
            (session["organization_id"],),
        ).fetchall()
        outcomes = _load_dimensions(program["id"])["outcomes"]
    else:
        members = []
        outcomes = []
    return render_template("actions.html", program=program, actions=rows, outcomes=outcomes, members=members)


@bp.post("/actions/<int:action_id>/update")
@login_required
def action_update(action_id: int):
    program = require_program(edit=True)
    status = request.form.get("status")
    allowed = {"planned", "in_progress", "completed", "verified", "cancelled"}
    if status not in allowed:
        abort(400)
    with get_db() as db:
        existing = db.execute(
            """SELECT ia.*,action_record.course_id,action_record.campus
                 FROM improvement_actions ia
                 LEFT JOIN assessment_records action_record
                   ON action_record.id=ia.assessment_id
                  AND action_record.program_id=ia.program_id
                WHERE ia.id=? AND ia.program_id=?""",
            (action_id, program["id"]),
        ).fetchone()
        if not existing:
            abort(404)
        _require_current_record_access(
            program["id"], existing["course_id"], existing["campus"]
        )
        if g.membership["role"] not in MANAGER_ROLES and existing["owner_user_id"] != g.user["id"]:
            abort(403)
        db.execute(
            """UPDATE improvement_actions SET status=?, impact_summary=?,
               completed_at=CASE WHEN ? IN ('completed','verified') THEN CURRENT_TIMESTAMP ELSE NULL END
               WHERE id=? AND program_id=?""",
            (status, request.form.get("impact_summary", "").strip(), status, action_id, program["id"]),
        )
        audit("update", "improvement_action", action_id, {"status": status})
    flash("Improvement action updated.", "success")
    return redirect(url_for("platform.actions"))


@bp.route("/analytics")
@login_required
def analytics():
    program = require_program()
    filters = _analysis_filter_context(program["id"])
    records = list(
        _record_query(program["id"], filters["where"], filters["params"])
    )
    analysis = analyze_rows(records, campus_group=filters["comparison_group"])
    charts = (
        generate_charts(records, campus_group=filters["comparison_group"])
        if records
        else {}
    )
    if current_app.config.get("EDITION") != "utrgv_mece":
        charts.pop("campus_comparison", None)
    export_pairs = [
        (key, value)
        for key in request.args
        for value in request.args.getlist(key)
    ]
    if not any(key == "evidence_scope" for key, _ in export_pairs):
        export_pairs.append(("evidence_scope", filters["evidence_scope"]))
    export_url = url_for("platform.export_csv")
    if export_pairs:
        export_url = f"{export_url}?{urlencode(export_pairs)}"
    scope_pairs = [
        (key, value) for key, value in export_pairs if key != "evidence_scope"
    ]
    preview_url = (
        f"{url_for('platform.analytics')}?"
        f"{urlencode([*scope_pairs, ('evidence_scope', 'all')])}"
    )
    official_url = (
        f"{url_for('platform.analytics')}?"
        f"{urlencode([*scope_pairs, ('evidence_scope', 'approved')])}"
    )
    return render_template(
        "analytics.html", program=program, records=records,
        analysis=analysis, charts=charts,
        metrics=summarize_records(records),
        scope_metrics=_analysis_scope_metrics(records),
        by_outcome=aggregate(records, "outcome") if records else [],
        by_course=aggregate(records, "course") if records else [],
        selected_course_ids=filters["selected_course_ids"],
        selected_campuses=filters["selected_campuses"],
        comparison_group=filters["comparison_group"],
        campuses=filters["available_campuses"],
        allowed_course_campus_pairs=filters["allowed_course_campus_pairs"],
        allowed_campuses_by_course=filters["allowed_campuses_by_course"],
        evidence_scope=filters["evidence_scope"], export_url=export_url,
        preview_url=preview_url, official_url=official_url,
        dimensions=filters["dimensions"],
        **filters["dimensions"],
    )


@bp.route("/report")
@login_required
def report():
    program = require_program()
    report_where = " AND ar.status='approved'"
    unresolved_campus_count = 0
    if current_app.config.get("EDITION") == "utrgv_mece":
        unresolved_scope, unresolved_scope_params = _faculty_record_scope_sql(
            program["id"], "ar.course_id", "ar.campus"
        )
        unresolved_campus_count = get_db().execute(
            f"""SELECT COUNT(*) FROM assessment_records ar
                WHERE ar.program_id=? AND ar.campus='Unassigned'
                {unresolved_scope}""",
            (program["id"], *unresolved_scope_params),
        ).fetchone()[0]
        report_where += " AND ar.campus IN ('Edinburg','Brownsville')"
    records = list(_record_query(program["id"], report_where))
    outcomes = aggregate(records, "outcome") if records else []
    report_analysis = analyze_rows(records, campus_group="outcome")
    report_charts = generate_charts(records, campus_group="outcome") if records else {}
    action_scope, action_scope_params = _faculty_record_scope_sql(
        program["id"], "action_record.course_id", "action_record.campus"
    )
    actions = get_db().execute(
        f"""SELECT ia.*,o.code AS outcome_code,u.full_name AS owner_name
              FROM improvement_actions ia
              LEFT JOIN outcomes o ON o.id=ia.outcome_id
              LEFT JOIN users u ON u.id=ia.owner_user_id
              LEFT JOIN assessment_records action_record
                ON action_record.id=ia.assessment_id
               AND action_record.program_id=ia.program_id
             WHERE ia.program_id=?{action_scope}
             ORDER BY ia.created_at""",
        (program["id"], *action_scope_params),
    ).fetchall()
    faculty_scope = _faculty_course_ids(program["id"])
    if faculty_scope is None:
        evidence = get_db().execute(
            """SELECT * FROM evidence_items
                WHERE program_id=? AND organization_id=? ORDER BY created_at""",
            (program["id"], session["organization_id"]),
        ).fetchall()
    else:
        evidence_scope, evidence_scope_params = _faculty_record_scope_sql(
            program["id"], "evidence_record.course_id", "evidence_record.campus"
        )
        campus_scope = (
            " AND evidence_record.campus IN ('Edinburg','Brownsville')"
            if current_app.config.get("EDITION") == "utrgv_mece"
            else ""
        )
        evidence = get_db().execute(
            f"""SELECT e.*
                  FROM evidence_items e
                  JOIN assessment_records evidence_record
                    ON evidence_record.id=e.assessment_id
                   AND evidence_record.program_id=e.program_id
                 WHERE e.program_id=? AND e.organization_id=?
                   AND evidence_record.status='approved'{campus_scope}
                   {evidence_scope}
                 ORDER BY e.created_at""",
            (
                program["id"],
                session["organization_id"],
                *evidence_scope_params,
            ),
        ).fetchall()
    return render_template(
        "report.html",
        program=program,
        records=records,
        outcomes=outcomes,
        campus_summaries=report_analysis["campuses"],
        campus_comparison=report_analysis["campus_comparison"],
        campus_chart=report_charts.get("campus_comparison"),
        campus_trends=report_analysis.get("campus_trends", []),
        campus_trend_chart=report_charts.get("trend_line"),
        unresolved_campus_count=unresolved_campus_count,
        actions=actions,
        evidence=evidence,
    )


@bp.get("/export/assessments.csv")
@login_required
def export_csv():
    program = require_program()
    filters = _analysis_filter_context(
        program["id"],
        default_scope="all",
        include_unassigned_when_unfiltered=(
            current_app.config.get("EDITION") == "utrgv_mece"
            and not request.args.getlist("campus")
            and "evidence_scope" not in request.args
        ),
    )
    records = list(
        _record_query(program["id"], filters["where"], filters["params"])
    )
    output = io.StringIO()
    percentage_export = current_app.config.get("EDITION") == "utrgv_mece"
    scoring_fields = (
        ["expert_percent", "practitioner_percent", "apprentice_percent", "novice_percent"]
        if percentage_export
        else ["sample_size"]
    )
    fields = [
        "campus", "term", "course", "outcome", "indicator", "method",
        "assessment_tool", "bloom_level", *scoring_fields, "result_basis",
        "source_record_id", "target", "attainment", "status", "rationale",
        "observations", "action_notes", "administrator_changed",
        "administrator_change_note", "administrator_changed_by",
        "administrator_changed_at",
    ]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for row in records:
        exported = {
            "campus": row["campus"], "term": row["term_label"], "course": row["course_label"].split(" — ")[0],
            "outcome": row["outcome_label"].split(":", 1)[0], "indicator": row["indicator_label"].split(":", 1)[0],
            "method": row["method"], "assessment_tool": row["assessment_tool"], "bloom_level": row["bloom_level"],
            "sample_size": "" if row["legacy_import_id"] else (row["sample_size"] or ""),
            "expert_percent": row["expert_percent"] if percentage_export else "",
            "practitioner_percent": row["practitioner_percent"] if percentage_export else "",
            "apprentice_percent": row["apprentice_percent"] if percentage_export else "",
            "novice_percent": row["novice_percent"] if percentage_export else "",
            "result_basis": (
                "source_percentages" if row["legacy_import_id"]
                and not percentage_export else row["result_basis"]
            ),
            "source_record_id": row["legacy_source_record_id"] or "",
            "target": row["target"], "attainment": row["attainment"],
            "status": row["status"], "rationale": row["rationale"], "observations": row["observations"],
            "action_notes": row["action_notes"],
            "administrator_changed": "yes" if row["admin_revision_count"] else "no",
            "administrator_change_note": row["admin_change_note"] or "",
            "administrator_changed_by": row["admin_changed_by"] or "",
            "administrator_changed_at": row["admin_changed_at"] or "",
        }
        writer.writerow({key: _csv_safe(exported.get(key, "")) for key in fields})
    filename = secure_filename(f"{program['code']}_assessment_export.csv")
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename={filename}"})


@bp.post("/import/assessments.csv")
@role_required("coordinator")
def import_csv():
    """Import UTRGV percentages or generic counts as tenant-scoped drafts."""
    program = require_program(edit=True)
    percentage_entry = current_app.config.get("EDITION") == "utrgv_mece"
    upload = request.files.get("file")
    if not upload or not upload.filename or Path(upload.filename).suffix.lower() != ".csv":
        abort(400, "Choose a CSV file.")
    try:
        text_stream = io.TextIOWrapper(upload.stream, encoding="utf-8-sig", newline="")
        reader = csv.DictReader(text_stream)
        if not reader.fieldnames:
            raise ValueError("The CSV file has no header row.")
        db = get_db()
        terms = {row["name"].casefold(): row for row in db.execute("SELECT * FROM academic_terms WHERE program_id=?", (program["id"],))}
        courses = {row["code"].casefold(): row for row in db.execute("SELECT * FROM courses WHERE program_id=?", (program["id"],))}
        outcomes = {row["code"].casefold(): row for row in db.execute("SELECT * FROM outcomes WHERE program_id=?", (program["id"],))}
        indicators = {}
        for row in db.execute(
            "SELECT pi.*,o.code AS outcome_code FROM performance_indicators pi JOIN outcomes o ON o.id=pi.outcome_id WHERE o.program_id=?",
            (program["id"],),
        ):
            indicators[(row["outcome_code"].casefold(), row["code"].casefold())] = row
        rubrics = {row["name"].casefold(): row for row in db.execute("SELECT * FROM rubrics WHERE program_id=?", (program["id"],))}
        imported = 0
        with db:
            for line_number, source in enumerate(reader, 2):
                if line_number > 1001:
                    raise ValueError("Imports are limited to 1,000 records at a time.")
                try:
                    term = terms[source.get("term", "").strip().casefold()]
                    course = courses[source.get("course", "").strip().casefold()]
                    outcome_code = source.get("outcome", "").strip().casefold()
                    outcome = outcomes[outcome_code]
                    indicator = indicators[(outcome_code, source.get("indicator", "").strip().casefold())]
                    rubric = rubrics[source.get("rubric", "").strip().casefold()]
                    target = parse_percent(
                        source.get("target")
                        if percentage_entry
                        else source.get("target") or program["default_target"]
                    )
                    levels = db.execute(
                        """SELECT * FROM rubric_levels WHERE rubric_id=?
                           ORDER BY display_order,id""",
                        (rubric["id"],),
                    ).fetchall()
                    if percentage_entry:
                        if rubric["name"].casefold() != "epan":
                            raise ValueError("UTRGV assessment records require the EPAN rubric")
                        percentages = _utrgv_epan_percentages(source, levels)
                        from .legacy_import import _scaled_counts

                        sample_size = None
                        result_basis = "percentages"
                        result_rows = [
                            (level["id"], count, percent)
                            for level, count, percent in zip(
                                levels,
                                _scaled_counts(percentages),
                                percentages,
                                strict=True,
                            )
                        ]
                    else:
                        sample_size = parse_int(source.get("sample_size"), minimum=1)
                        counts = [
                            (
                                level["id"],
                                parse_int(source.get(level["label"], 0), minimum=0),
                            )
                            for level in levels
                        ]
                        if sum(count for _, count in counts) != sample_size:
                            raise ValueError("rubric counts do not equal sample_size")
                        result_basis = "student_counts"
                        result_rows = [
                            (level_id, count, None) for level_id, count in counts
                        ]
                    method = source.get(
                        "method", "" if percentage_entry else "direct"
                    ).strip().lower()
                    if method not in {"direct", "indirect"}:
                        raise ValueError("method must be direct or indirect")
                    tool = _required_text(
                        source.get("assessment_tool"), "assessment_tool"
                    )
                    bloom_level = source.get("bloom_level", "").strip()
                    rationale = source.get("rationale", "").strip()
                    observations = source.get("observations", "").strip()
                    action_notes = source.get("action_notes", "").strip()
                    if percentage_entry:
                        bloom_level = _required_text(bloom_level, "bloom_level")
                        rationale = _required_text(rationale, "rationale")
                        observations = _required_text(observations, "observations")
                        action_notes = _required_text(action_notes, "action_notes")
                    campus = _assessment_campus(
                        source.get("campus"),
                        required=current_app.config["EDITION"] == "utrgv_mece",
                    )
                    assessment_id = db.execute(
                        """INSERT INTO assessment_records
                           (program_id,term_id,course_id,outcome_id,indicator_id,rubric_id,collected_by,method,
                            assessment_tool,bloom_level,sample_size,result_basis,target,rationale,observations,action_notes,campus)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (program["id"], term["id"], course["id"], outcome["id"], indicator["id"], rubric["id"],
                         g.user["id"], method, tool, bloom_level, sample_size, result_basis, target,
                         rationale, observations, action_notes, campus),
                    ).lastrowid
                    db.executemany(
                        """INSERT INTO assessment_results
                           (assessment_id,rubric_level_id,student_count,level_percent)
                           VALUES (?,?,?,?)""",
                        [
                            (assessment_id, level_id, count, percent)
                            for level_id, count, percent in result_rows
                        ],
                    )
                    imported += 1
                except (KeyError, ValueError) as error:
                    raise ValueError(f"Row {line_number}: {error}") from None
            audit("import", "assessment", details={"rows": imported, "filename": secure_filename(upload.filename)})
        flash(f"Imported {imported} draft assessment record(s).", "success")
    except (UnicodeDecodeError, csv.Error, ValueError, sqlite3.IntegrityError) as error:
        flash_validation(error)
    return redirect(url_for("platform.assessments"))


@bp.get("/import/template.csv")
@role_required("coordinator")
def import_template():
    program = require_program()
    rubric = get_db().execute(
        "SELECT * FROM rubrics WHERE program_id=? ORDER BY is_default DESC,name LIMIT 1", (program["id"],)
    ).fetchone()
    levels = get_db().execute(
        "SELECT label FROM rubric_levels WHERE rubric_id=? ORDER BY display_order", (rubric["id"] if rubric else -1,)
    ).fetchall()
    if current_app.config.get("EDITION") == "utrgv_mece":
        scoring_fields = [
            "expert_percent",
            "practitioner_percent",
            "apprentice_percent",
            "novice_percent",
        ]
    else:
        scoring_fields = ["sample_size", *[row["label"] for row in levels]]
    fields = [
        "campus", "term", "course", "outcome", "indicator", "rubric",
        "method", "assessment_tool", "bloom_level", *scoring_fields,
        "target", "rationale", "observations", "action_notes",
    ]
    output = io.StringIO()
    csv.DictWriter(output, fieldnames=fields).writeheader()
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=assessment_import_template.csv"})


@bp.route("/utrgv/support-account", methods=["GET", "POST"])
@role_required("owner")
def utrgv_support_account():
    """Create and control the one owner-managed faculty-view identity."""
    if current_app.config.get("EDITION") != "utrgv_mece":
        abort(404)
    program = require_program(edit=True)
    destination = f"{url_for('platform.users')}#faculty-view-support"
    if request.method == "GET":
        return redirect(destination)
    db = get_db()
    raw_marker = db.execute(
        """SELECT psa.program_id,psa.user_id
             FROM program_support_accounts psa
             JOIN programs p ON p.id=psa.program_id
            WHERE psa.program_id=? AND p.organization_id=?""",
        (program["id"], session["organization_id"]),
    ).fetchone()
    account = _program_support_account(
        program["id"], session["organization_id"]
    )
    if raw_marker and not account:
        abort(
            409,
            "The faculty-view marker is inconsistent. Repair its Faculty/editor "
            "membership before changing credentials.",
        )
    action = request.form.get("action", "").strip().lower()
    try:
        if action == "create":
            if raw_marker:
                raise ValueError(
                    "This program already has a faculty-view support account."
                )
            full_name, username, email = _support_identity_fields(program["id"])
            password = _owner_supplied_temporary_password()
            with db:
                user_id = db.execute(
                    """INSERT INTO users
                       (email,username,full_name,password_hash,must_change_password)
                       VALUES (?,?,?,?,1)""",
                    (
                        email,
                        username,
                        full_name,
                        generate_password_hash(password),
                    ),
                ).lastrowid
                db.execute(
                    """INSERT INTO memberships(user_id,organization_id,role)
                       VALUES (?,?,'faculty')""",
                    (user_id, session["organization_id"]),
                )
                db.execute(
                    """INSERT INTO program_members(program_id,user_id,access_level)
                       VALUES (?,?,'editor')""",
                    (program["id"], user_id),
                )
                db.execute(
                    """INSERT INTO program_support_accounts
                       (program_id,user_id,configured_by) VALUES (?,?,?)""",
                    (program["id"], user_id, g.user["id"]),
                )
                audit(
                    "create",
                    "program_support_account",
                    user_id,
                    {
                        "program_id": program["id"],
                        "role": "faculty",
                        "access_level": "editor",
                        "scope_selected": False,
                        "temporary_password_owner_supplied": True,
                    },
                )
            flash(
                "Faculty-view support account created. Share the temporary "
                "password securely; the account must replace it at first sign-in.",
                "success",
            )
        elif action == "update":
            if not account:
                raise ValueError("Create the faculty-view support account first.")
            full_name, username, email = _support_identity_fields(
                program["id"], existing_user_id=account["user_id"]
            )
            before = {
                "full_name": account["full_name"],
                "email": account["email"],
                "username": account["username"],
            }
            with db:
                db.execute(
                    """UPDATE users SET full_name=?,email=?,username=?
                       WHERE id=?""",
                    (full_name, email, username, account["user_id"]),
                )
                db.execute(
                    """UPDATE program_support_accounts
                       SET configured_by=?,updated_at=CURRENT_TIMESTAMP
                       WHERE program_id=? AND user_id=?""",
                    (g.user["id"], program["id"], account["user_id"]),
                )
                audit(
                    "update",
                    "program_support_account",
                    account["user_id"],
                    {
                        "before": before,
                        "after": {
                            "full_name": full_name,
                            "email": email,
                            "username": username,
                        },
                    },
                )
            flash("Faculty-view support identity updated.", "success")
        elif action == "reset_password":
            if not account:
                raise ValueError("Create the faculty-view support account first.")
            password = _owner_supplied_temporary_password()
            with db:
                db.execute(
                    """UPDATE users SET password_hash=?,must_change_password=1
                       WHERE id=?""",
                    (generate_password_hash(password), account["user_id"]),
                )
                db.execute(
                    """UPDATE program_support_accounts
                       SET configured_by=?,updated_at=CURRENT_TIMESTAMP
                       WHERE program_id=? AND user_id=?""",
                    (g.user["id"], program["id"], account["user_id"]),
                )
                identifiers = {account["email"].casefold()}
                if account["username"]:
                    identifiers.add(account["username"].casefold())
                db.executemany(
                    "DELETE FROM login_attempts WHERE email=?",
                    [(identifier,) for identifier in identifiers],
                )
                audit(
                    "reset",
                    "program_support_account_password",
                    account["user_id"],
                    {"force_password_change": True, "owner_controlled": True},
                )
            flash(
                "Temporary password reset. The faculty-view account must replace "
                "it at next sign-in.",
                "success",
            )
        elif action == "disable":
            if not account:
                raise ValueError("Create the faculty-view support account first.")
            with db:
                db.execute(
                    "UPDATE users SET is_active=0 WHERE id=?",
                    (account["user_id"],),
                )
                db.execute(
                    """UPDATE program_support_accounts
                       SET configured_by=?,updated_at=CURRENT_TIMESTAMP
                       WHERE program_id=? AND user_id=?""",
                    (g.user["id"], program["id"], account["user_id"]),
                )
                audit(
                    "disable",
                    "program_support_account",
                    account["user_id"],
                    {"owner_controlled": True},
                )
            flash("Faculty-view support account disabled.", "success")
        elif action == "reactivate":
            if not account:
                raise ValueError("Create the faculty-view support account first.")
            password = _owner_supplied_temporary_password()
            with db:
                db.execute(
                    """UPDATE users SET is_active=1,password_hash=?,
                       must_change_password=1 WHERE id=?""",
                    (generate_password_hash(password), account["user_id"]),
                )
                db.execute(
                    """UPDATE program_support_accounts
                       SET configured_by=?,updated_at=CURRENT_TIMESTAMP
                       WHERE program_id=? AND user_id=?""",
                    (g.user["id"], program["id"], account["user_id"]),
                )
                identifiers = {account["email"].casefold()}
                if account["username"]:
                    identifiers.add(account["username"].casefold())
                db.executemany(
                    "DELETE FROM login_attempts WHERE email=?",
                    [(identifier,) for identifier in identifiers],
                )
                audit(
                    "reactivate",
                    "program_support_account",
                    account["user_id"],
                    {
                        "force_password_change": True,
                        "temporary_password_owner_supplied": True,
                    },
                )
            flash(
                "Faculty-view support account reactivated with an owner-supplied "
                "temporary password.",
                "success",
            )
        else:
            abort(400, "Unknown faculty-view account action.")
    except (ValueError, sqlite3.IntegrityError) as error:
        flash_validation(error)
    return redirect(destination)


@bp.route("/utrgv/support-scope", methods=["GET", "POST"])
@login_required
def utrgv_support_scope():
    """Allow only the marked support identity to choose one real-data scope."""
    if current_app.config.get("EDITION") != "utrgv_mece":
        abort(404)
    program = require_program(edit=True)
    account = _program_support_account(
        program["id"],
        session["organization_id"],
        user_id=g.user["id"],
    )
    if not account:
        abort(403)
    db = get_db()
    courses = db.execute(
        """SELECT id,code,name FROM courses
           WHERE program_id=? AND is_active=1 ORDER BY code""",
        (program["id"],),
    ).fetchall()
    state = _support_scope_state(program["id"], g.user["id"])
    if request.method == "POST":
        try:
            course_id = parse_int(request.form.get("course_id"), minimum=1)
            course = db.execute(
                """SELECT id,code FROM courses
                   WHERE id=? AND program_id=? AND is_active=1""",
                (course_id, program["id"]),
            ).fetchone()
            if not course:
                raise ValueError("Choose an active course in this program.")
            selected_campuses = {
                _assessment_campus(value, required=True)
                for value in request.form.getlist("campus")
                if str(value).strip()
            }
            if not 1 <= len(selected_campuses) <= 2:
                raise ValueError("Choose Edinburg, Brownsville, or both campuses.")
            ordered_campuses = tuple(
                campus
                for campus in UTRGV_CAMPUSES
                if campus in selected_campuses
            )
            before_pairs = db.execute(
                """SELECT cca.course_id,cca.campus
                     FROM course_campus_assignments cca
                     JOIN courses c ON c.id=cca.course_id
                    WHERE cca.user_id=? AND c.program_id=?
                    ORDER BY cca.course_id,cca.campus""",
                (g.user["id"], program["id"]),
            ).fetchall()
            before = [
                (row["course_id"], row["campus"]) for row in before_pairs
            ]
            after = [(course_id, campus) for campus in ordered_campuses]
            with db:
                # Scope changes are deliberately limited to this user and the
                # current program. Assignments in another program are untouched.
                db.execute(
                    """DELETE FROM course_campus_assignments
                       WHERE user_id=? AND course_id IN
                             (SELECT id FROM courses WHERE program_id=?)""",
                    (g.user["id"], program["id"]),
                )
                db.execute(
                    """DELETE FROM course_assignments
                       WHERE user_id=? AND course_id IN
                             (SELECT id FROM courses WHERE program_id=?)""",
                    (g.user["id"], program["id"]),
                )
                db.execute(
                    "INSERT INTO course_assignments(course_id,user_id) VALUES (?,?)",
                    (course_id, g.user["id"]),
                )
                db.executemany(
                    """INSERT INTO course_campus_assignments
                       (course_id,user_id,campus) VALUES (?,?,?)""",
                    [
                        (course_id, g.user["id"], campus)
                        for campus in ordered_campuses
                    ],
                )
                audit(
                    "update_scope",
                    "program_support_account",
                    g.user["id"],
                    {
                        "program_id": program["id"],
                        "before": before,
                        "after": after,
                        "real_data_access": True,
                        "writes_are_real_and_audited": True,
                    },
                )
            flash(
                f"Faculty-view scope changed to {course['code']} — "
                f"{', '.join(ordered_campuses)}. This uses real program data; "
                "any records entered or changed are saved and permanently audited.",
                "warning",
            )
            return redirect(url_for("platform.dashboard"))
        except (ValueError, sqlite3.IntegrityError) as error:
            flash_validation(error)
    return render_template(
        "faculty_preview.html",
        program=program,
        courses=courses,
        campuses=UTRGV_CAMPUSES,
        selected_course_id=state["course_id"],
        selected_campuses=set(state["campuses"]),
    )


@bp.route("/users", methods=["GET", "POST"])
@role_required("admin")
def users():
    program = require_program(edit=True)
    db = get_db()
    if request.method == "POST":
        try:
            email = request.form.get("email", "").strip().lower()
            username = request.form.get("username", "").strip() or None
            full_name = request.form.get("full_name", "").strip()
            password = request.form.get("temporary_password", "")
            role = request.form.get("role", "faculty")
            if "@" not in email or not full_name or len(password) < 12 or role not in {"admin", "coordinator", "faculty", "reviewer"}:
                raise ValueError("Provide a name, valid email, role, and temporary password of at least 12 characters.")
            if current_app.config.get("EDITION") == "utrgv_mece" and role == "faculty":
                abort(
                    403,
                    "UTRGV faculty accounts must be created from an owner-approved invitation.",
                )
            if current_app.config.get("EDITION") == "utrgv_mece" and db.execute(
                """SELECT 1 FROM faculty_roster
                    WHERE program_id=? AND approved_email=?""",
                (program["id"], email),
            ).fetchone():
                abort(
                    403,
                    "That email is reserved for its approved UTRGV faculty invitation.",
                )
            if g.membership["role"] != "owner" and role == "admin":
                abort(403)
            with db:
                existing = db.execute(
                    """SELECT u.id,m.role FROM users u
                       LEFT JOIN memberships m ON m.user_id=u.id AND m.organization_id=?
                       WHERE u.email=? OR (? IS NOT NULL AND u.username=?)""",
                    (session["organization_id"], email, username, username),
                ).fetchone()
                if existing:
                    if not existing["role"]:
                        raise ValueError("That account already belongs to another organization. Contact support to link it safely.")
                    if existing["id"] == g.user["id"]:
                        raise ValueError("Use Change password to update your own account.")
                    if db.execute(
                        """SELECT 1 FROM program_support_accounts psa
                           JOIN programs p ON p.id=psa.program_id
                           WHERE psa.user_id=? AND p.organization_id=?""",
                        (existing["id"], session["organization_id"]),
                    ).fetchone():
                        abort(
                            403,
                            "Use the owner-controlled faculty-view support card "
                            "to manage this account.",
                        )
                    if g.membership["role"] != "owner" and existing["role"] in {"owner", "admin"}:
                        abort(403)
                    if current_app.config.get("EDITION") == "utrgv_mece" and db.execute(
                        """SELECT 1 FROM faculty_roster
                            WHERE program_id=? AND user_id=?""",
                        (program["id"], existing["id"]),
                    ).fetchone():
                        abort(
                            403,
                            "Use the UTRGV faculty roster to change faculty access.",
                        )
                    user_id = existing["id"]
                    db.execute(
                        """UPDATE users SET email=?,username=?,full_name=?,password_hash=?,
                           must_change_password=1,is_active=1 WHERE id=?""",
                        (email, username, full_name, generate_password_hash(password), user_id),
                    )
                else:
                    user_id = db.execute(
                        """INSERT INTO users(email,username,full_name,password_hash,must_change_password)
                           VALUES (?,?,?,?,1)""",
                        (email, username, full_name, generate_password_hash(password)),
                    ).lastrowid
                db.execute(
                    "INSERT INTO memberships(user_id,organization_id,role) VALUES (?,?,?) ON CONFLICT(user_id,organization_id) DO UPDATE SET role=excluded.role",
                    (user_id, session["organization_id"], role),
                )
                access_level = "viewer" if role == "reviewer" else "editor"
                db.execute(
                    "INSERT INTO program_members(program_id,user_id,access_level) VALUES (?,?,?) ON CONFLICT(program_id,user_id) DO UPDATE SET access_level=excluded.access_level",
                    (program["id"], user_id, access_level),
                )
                course_ids = {course["id"] for course in _load_dimensions(program["id"])["courses"]}
                db.execute(
                    """DELETE FROM course_assignments WHERE user_id=? AND course_id IN
                       (SELECT id FROM courses WHERE program_id=?)""",
                    (user_id, program["id"]),
                )
                if current_app.config.get("EDITION") == "utrgv_mece":
                    db.execute(
                        """DELETE FROM course_campus_assignments
                           WHERE user_id=? AND course_id IN
                                 (SELECT id FROM courses WHERE program_id=?)""",
                        (user_id, program["id"]),
                    )
                for raw in request.form.getlist("course_ids"):
                    course_id = parse_int(raw, minimum=1)
                    if course_id in course_ids:
                        db.execute("INSERT OR IGNORE INTO course_assignments(course_id,user_id) VALUES (?,?)", (course_id, user_id))
                        if (
                            current_app.config.get("EDITION") == "utrgv_mece"
                            and role == "reviewer"
                        ):
                            db.executemany(
                                """INSERT OR IGNORE INTO course_campus_assignments
                                   (course_id,user_id,campus) VALUES (?,?,?)""",
                                [
                                    (course_id, user_id, campus)
                                    for campus in UTRGV_CAMPUSES
                                ],
                            )
                audit(
                    "update" if existing else "create",
                    "user_access",
                    user_id,
                    {"role": role, "program_id": program["id"]},
                )
            flash("User access saved. Share the temporary password through a secure channel.", "success")
            return redirect(url_for("platform.users"))
        except (ValueError, sqlite3.IntegrityError) as error:
            flash_validation(error)
    rows = db.execute(
        """SELECT u.id,u.full_name,u.email,u.username,u.is_active,u.must_change_password,
                  m.role,pm.access_level,
                  GROUP_CONCAT(c.code, ', ') AS courses
           FROM users u JOIN memberships m ON m.user_id=u.id AND m.organization_id=?
           LEFT JOIN program_members pm ON pm.user_id=u.id AND pm.program_id=?
           LEFT JOIN course_assignments ca ON ca.user_id=u.id
           LEFT JOIN courses c ON c.id=ca.course_id AND c.program_id=?
           GROUP BY u.id,m.role,pm.access_level ORDER BY u.full_name""",
        (session["organization_id"], program["id"], program["id"]),
    ).fetchall()
    faculty_roster = []
    support_account = None
    if current_app.config.get("EDITION") == "utrgv_mece":
        support_user_ids = {
            row["user_id"]
            for row in db.execute(
                """SELECT psa.user_id FROM program_support_accounts psa
                   JOIN programs p ON p.id=psa.program_id
                   WHERE p.organization_id=?""",
                (session["organization_id"],),
            )
        }
        rows = [item for item in rows if item["id"] not in support_user_ids]
        support_account = _support_account_context(
            program["id"], session["organization_id"]
        )
        if support_account:
            rows = [
                item
                for item in rows
                if item["id"] != support_account["user_id"]
            ]
        roster_rows = _enrich_utrgv_roster_rows(db.execute(
            """SELECT fr.id AS roster_id,fr.display_name,fr.approved_email,
                      fr.user_id,fr.status AS roster_status,
                      u.email AS account_email,u.username,u.is_active,
                      u.must_change_password,pm.access_level
                 FROM faculty_roster fr
                 LEFT JOIN users u ON u.id=fr.user_id
                 LEFT JOIN program_members pm ON pm.user_id=fr.user_id
                                             AND pm.program_id=fr.program_id
                WHERE fr.program_id=?
                ORDER BY fr.display_name""",
            (program["id"],),
        ).fetchall(), program["id"])
        linked_faculty_ids = {
            item["user_id"] for item in roster_rows if item["user_id"] is not None
        }
        # Active faculty appear through their approved roster identity below. Keeping
        # them out of the general account rows prevents a faculty member from being
        # shown twice while pending invitations remain visible before activation.
        rows = [item for item in rows if item["id"] not in linked_faculty_ids]
        for item in roster_rows:
            faculty = dict(item)
            if not item["user_id"] and item["roster_status"] == "pending":
                faculty["account_status"] = "Pending activation"
                faculty["status_class"] = "draft"
            elif item["roster_status"] == "active" and item["is_active"]:
                faculty["account_status"] = "Active"
                faculty["status_class"] = "approved"
            else:
                faculty["account_status"] = "Inactive"
                faculty["status_class"] = "returned"
            faculty_roster.append(faculty)
    return render_template(
        "users.html",
        program=program,
        users=rows,
        faculty_roster=faculty_roster,
        support_account=support_account,
        courses=_load_dimensions(program["id"])["courses"],
    )


@bp.post("/users/<int:user_id>/temporary-password")
@role_required("admin")
def set_temporary_password(user_id: int):
    """Let a tenant administrator recover an active user's account safely."""
    require_program(edit=True)
    db = get_db()
    target = db.execute(
        """SELECT u.id,u.email,u.username,u.full_name,u.is_active,m.role
             FROM users u
             JOIN memberships m ON m.user_id=u.id
            WHERE u.id=? AND m.organization_id=?""",
        (user_id, session["organization_id"]),
    ).fetchone()
    if not target:
        abort(404)
    if not target["is_active"]:
        abort(400, "A temporary password can only be set for an active account.")
    if target["id"] == g.user["id"]:
        abort(400, "Use Change password to update your own account.")
    if get_db().execute(
        """SELECT 1 FROM program_support_accounts psa
           JOIN programs p ON p.id=psa.program_id
           WHERE psa.user_id=? AND p.organization_id=?""",
        (target["id"], session["organization_id"]),
    ).fetchone() and g.membership["role"] != "owner":
        abort(
            403,
            "Only the owner can reset the faculty-view support credential.",
        )
    if g.membership["role"] != "owner" and target["role"] in {"owner", "admin"}:
        abort(403)

    password = request.form.get("temporary_password", "")
    if len(password) < 12:
        flash("The temporary password must contain at least 12 characters.", "error")
    elif password != request.form.get("confirm_temporary_password"):
        flash("Temporary password entries do not match.", "error")
    else:
        with db:
            db.execute(
                "UPDATE users SET password_hash=?,must_change_password=1 WHERE id=?",
                (generate_password_hash(password), target["id"]),
            )
            identifiers = [target["email"].casefold()]
            if target["username"]:
                identifiers.append(target["username"].casefold())
            db.executemany("DELETE FROM login_attempts WHERE email=?", [(value,) for value in identifiers])
            audit(
                "reset",
                "password",
                target["id"],
                {"force_password_change": True, "target_role": target["role"]},
            )
        flash(
            f"Temporary password set for {target['full_name']}. Share it through a secure channel; "
            "the user must replace it at the next sign-in.",
            "success",
        )
    fallback = url_for("platform.users")
    return redirect(safe_next_url(request.form.get("next")) or fallback)


@bp.get("/audit")
@role_required("admin")
def audit_log():
    program = require_program()
    rows = get_db().execute(
        """SELECT ae.*,u.full_name FROM audit_events ae LEFT JOIN users u ON u.id=ae.user_id
           WHERE ae.organization_id=? ORDER BY ae.created_at DESC LIMIT 500""", (session["organization_id"],)
    ).fetchall()
    return render_template("audit.html", program=program, events=rows)


@bp.get("/utrgv/legacy")
@role_required("coordinator")
def legacy_archive():
    if current_app.config["EDITION"] != "utrgv_mece":
        abort(404)
    program = require_program()
    sources = _configured_legacy_sources()
    source_key = request.args.get("source", next(iter(sources)))
    selected_source = sources.get(source_key)
    if not selected_source:
        abort(400, "Unknown assessment source.")
    source = selected_source["path"] or ""
    error = None
    metadata = summary = options = result = None
    drafts = []
    try:
        from .legacy_reader import (
            LegacyReaderError,
            filter_options,
            list_drafts,
            list_records,
            source_metadata,
            summarize_records,
        )

        filters = {
            "course": request.args.get("course"),
            "semester": request.args.get("semester"),
            "slo": request.args.get("slo"),
            "search": request.args.get("search"),
        }
        metadata = source_metadata(source)
        summary = summarize_records(source, **filters)
        options = filter_options(source)
        result = list_records(
            source,
            **filters,
            page=parse_int(request.args.get("page", 1), minimum=1),
            per_page=50,
        )
        drafts = list_drafts(source)
    except (LegacyReaderError, ValueError) as caught:
        error = str(caught)
    return render_template(
        "legacy_archive.html", program=program, metadata=metadata, summary=summary,
        options=options, result=result, drafts=drafts, source_error=error,
        sources=list(sources.values()), selected_source=selected_source,
        unassigned_count=get_db().execute(
            """SELECT COUNT(*) FROM assessment_records ar
               JOIN legacy_import_items li ON li.assessment_id=ar.id
               WHERE ar.program_id=? AND ar.campus='Unassigned'""",
            (program["id"],),
        ).fetchone()[0],
        campuses=UTRGV_CAMPUSES,
    )


@bp.post("/utrgv/legacy/import")
@role_required("coordinator")
def legacy_archive_import():
    if current_app.config["EDITION"] != "utrgv_mece":
        abort(404)
    program = require_program(edit=True)
    sources = _configured_legacy_sources()
    source_key = request.form.get("source_key", next(iter(sources)))
    selected_source = sources.get(source_key)
    if not selected_source:
        abort(400, "Unknown assessment source.")
    source = selected_source["path"] or ""
    try:
        from .legacy_import import import_legacy_records
        from .legacy_reader import LegacyReaderError

        campus = _assessment_campus(
            selected_source["campus"] or request.form.get("campus"), required=True
        )
        if selected_source["campus"] and campus != selected_source["campus"]:
            raise ValueError("The selected assessment source is assigned to another campus.")
        with get_db() as db:
            result = import_legacy_records(
                db,
                source,
                program_id=program["id"],
                imported_by=g.user["id"],
                campus=campus,
                source_key=source_key,
            )
            audit(
                "import",
                "utrgv_legacy_archive",
                details={
                    "imported": result["imported"],
                    "skipped": result["skipped"],
                    "content_fingerprint": result["content_fingerprint"],
                    "campus": campus,
                    "source_key": source_key,
                },
            )
        flash(
            f"Imported {result['imported']} {campus} current source row(s) as reviewable drafts; "
            f"{result['skipped']} already imported row(s) were skipped.",
            "success",
        )
    except (LegacyReaderError, ValueError, sqlite3.IntegrityError) as error:
        flash_validation(error)
    return redirect(url_for("platform.legacy_archive", source=source_key))


@bp.post("/utrgv/legacy/assign-campus")
@role_required("admin")
def legacy_assign_campus():
    """Resolve pre-campus source imports without changing their percentages."""
    if current_app.config["EDITION"] != "utrgv_mece":
        abort(404)
    program = require_program(edit=True)
    try:
        campus = _assessment_campus(request.form.get("campus"), required=True)
        with get_db() as db:
            records = db.execute(
                """SELECT ar.id,ar.status,ar.record_version
                     FROM assessment_records ar
                     JOIN legacy_import_items li ON li.assessment_id=ar.id
                                                AND li.program_id=ar.program_id
                    WHERE ar.program_id=? AND ar.campus='Unassigned'""",
                (program["id"],),
            ).fetchall()
            note = f"Campus assigned to {campus} by administrator."
            for record in records:
                updated = db.execute(
                    """UPDATE assessment_records
                       SET campus=?,status='draft',submitted_at=NULL,approved_at=NULL,
                           approved_by=NULL,record_version=record_version+1,
                           updated_at=CURRENT_TIMESTAMP
                       WHERE id=? AND program_id=? AND campus='Unassigned'
                         AND record_version=?""",
                    (
                        campus, record["id"], program["id"],
                        record["record_version"],
                    ),
                )
                if updated.rowcount != 1:
                    abort(
                        409,
                        "A source assessment changed while campuses were being "
                        "assigned. Refresh and try again.",
                    )
                db.execute(
                    """INSERT INTO assessment_revisions
                       (program_id,assessment_id,changed_by,changed_by_name,
                        change_note,before_json,after_json)
                       VALUES (?,?,?,?,?,?,?)""",
                    (
                        program["id"], record["id"], g.user["id"],
                        g.user["full_name"], note,
                        json.dumps(
                            {"campus": "Unassigned", "status": record["status"]},
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        json.dumps(
                            {"campus": campus, "status": "draft"},
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    ),
                )
            audit(
                "assign_campus",
                "utrgv_legacy_archive",
                details={
                    "campus": campus,
                    "records": len(records),
                    "administrative_change": True,
                    "review_reset": sum(
                        record["status"] in {"submitted", "approved"}
                        for record in records
                    ),
                },
            )
        flash(
            f"Assigned {len(records)} previously unresolved source row(s) to {campus}. "
            "Each record now includes a permanent administrative change note.",
            "success",
        )
    except (ValueError, sqlite3.IntegrityError) as error:
        flash_validation(error)
    return redirect(url_for("platform.legacy_archive"))


@bp.get("/utrgv/faculty")
@role_required("admin")
def utrgv_faculty():
    if current_app.config["EDITION"] != "utrgv_mece":
        abort(404)
    program = require_program()
    roster = _enrich_utrgv_roster_rows(get_db().execute(
        """SELECT fr.*,u.email,u.username,u.is_active,u.must_change_password
           FROM faculty_roster fr
           LEFT JOIN users u ON u.id=fr.user_id
           WHERE fr.program_id=?
           ORDER BY fr.display_name""",
        (program["id"],),
    ).fetchall(), program["id"])
    courses = get_db().execute(
        "SELECT id,code,name FROM courses WHERE program_id=? AND is_active=1 ORDER BY code",
        (program["id"],),
    ).fetchall()
    return render_template(
        "utrgv_faculty.html", program=program, roster=roster, courses=courses,
        campuses=UTRGV_CAMPUSES,
    )


@bp.post("/utrgv/faculty/invitations")
@role_required("owner")
def utrgv_faculty_invite():
    """Let the UTRGV owner add an email to the faculty invitation allowlist."""
    if current_app.config["EDITION"] != "utrgv_mece":
        abort(404)
    program = require_program(edit=True)
    db = get_db()
    try:
        display_name = request.form.get("display_name", "").strip()
        if not display_name:
            raise ValueError("Provide the faculty member's full name.")
        approved_email = _normalize_utrgv_email(request.form.get("approved_email"))
        course_campus_pairs = _utrgv_roster_course_campus_pairs(program["id"])
        course_ids = sorted({course_id for course_id, _ in course_campus_pairs})
        if db.execute(
            "SELECT 1 FROM users WHERE email=?", (approved_email,)
        ).fetchone():
            raise ValueError("That email already belongs to an account.")
        if db.execute(
            "SELECT 1 FROM faculty_roster WHERE program_id=? AND approved_email=?",
            (program["id"], approved_email),
        ).fetchone():
            raise ValueError("That email already has a faculty invitation.")
        with db:
            roster_id = db.execute(
                """INSERT INTO faculty_roster
                   (program_id,legacy_name,display_name,approved_email,status)
                   VALUES (?,?,?,?,'pending')""",
                (program["id"], display_name, display_name, approved_email),
            ).lastrowid
            db.executemany(
                """INSERT INTO faculty_roster_courses
                   (faculty_roster_id,course_id) VALUES (?,?)""",
                [(roster_id, course_id) for course_id in course_ids],
            )
            db.executemany(
                """INSERT INTO faculty_roster_course_campuses
                   (faculty_roster_id,course_id,campus) VALUES (?,?,?)""",
                [
                    (roster_id, course_id, campus)
                    for course_id, campus in course_campus_pairs
                ],
            )
            audit(
                "invite",
                "faculty_roster",
                roster_id,
                {
                    "approved_email": approved_email,
                    "course_ids": course_ids,
                    "course_campus_pairs": course_campus_pairs,
                    "account_created": False,
                    "owner_approved": True,
                },
            )
        flash(
            f"Invitation approved for {display_name}. An administrator may now activate the account.",
            "success",
        )
    except (ValueError, sqlite3.IntegrityError) as error:
        flash_validation(error)
    return redirect(url_for("platform.utrgv_faculty"))


@bp.post("/utrgv/faculty/<int:roster_id>/invitation")
@role_required("owner")
def utrgv_faculty_invitation_update(roster_id: int):
    """Change an allowlisted address/exact pair scope and sync an active account."""
    if current_app.config["EDITION"] != "utrgv_mece":
        abort(404)
    program = require_program(edit=True)
    db = get_db()
    roster = db.execute(
        """SELECT fr.*,u.email AS account_email,m.role AS account_role
             FROM faculty_roster fr
             LEFT JOIN users u ON u.id=fr.user_id
             LEFT JOIN memberships m ON m.user_id=fr.user_id
                                    AND m.organization_id=?
            WHERE fr.id=? AND fr.program_id=?""",
        (session["organization_id"], roster_id, program["id"]),
    ).fetchone()
    if not roster:
        abort(404)
    if roster["user_id"] and roster["account_role"] != "faculty":
        abort(400, "Only faculty accounts can be managed through the faculty roster.")
    try:
        display_name = request.form.get("display_name", "").strip()
        if not display_name:
            raise ValueError("Provide the faculty member's full name.")
        approved_email = _normalize_utrgv_email(request.form.get("approved_email"))
        course_campus_pairs = _utrgv_roster_course_campus_pairs(program["id"])
        course_ids = sorted({course_id for course_id, _ in course_campus_pairs})
        duplicate_roster = db.execute(
            """SELECT id FROM faculty_roster
                WHERE program_id=? AND approved_email=? AND id<>?""",
            (program["id"], approved_email, roster_id),
        ).fetchone()
        if duplicate_roster:
            raise ValueError("That email already has a faculty invitation.")
        duplicate_user = db.execute(
            "SELECT id FROM users WHERE email=? AND id<>?",
            (approved_email, roster["user_id"] or -1),
        ).fetchone()
        if duplicate_user:
            raise ValueError("That email already belongs to another account.")
        old_course_campus_pairs = [
            (row["course_id"], row["campus"])
            for row in db.execute(
                """SELECT course_id,campus
                     FROM faculty_roster_course_campuses
                    WHERE faculty_roster_id=?
                    ORDER BY course_id,
                             CASE campus WHEN 'Edinburg' THEN 1 ELSE 2 END""",
                (roster_id,),
            )
        ]
        with db:
            db.execute(
                """UPDATE faculty_roster
                   SET display_name=?,approved_email=? WHERE id=? AND program_id=?""",
                (display_name, approved_email, roster_id, program["id"]),
            )
            db.execute(
                "DELETE FROM faculty_roster_courses WHERE faculty_roster_id=?",
                (roster_id,),
            )
            db.execute(
                "DELETE FROM faculty_roster_course_campuses WHERE faculty_roster_id=?",
                (roster_id,),
            )
            db.executemany(
                """INSERT INTO faculty_roster_courses
                   (faculty_roster_id,course_id) VALUES (?,?)""",
                [(roster_id, course_id) for course_id in course_ids],
            )
            db.executemany(
                """INSERT INTO faculty_roster_course_campuses
                   (faculty_roster_id,course_id,campus) VALUES (?,?,?)""",
                [
                    (roster_id, course_id, campus)
                    for course_id, campus in course_campus_pairs
                ],
            )
            if roster["user_id"]:
                db.execute(
                    "UPDATE users SET full_name=?,email=? WHERE id=?",
                    (display_name, approved_email, roster["user_id"]),
                )
                db.execute(
                    """DELETE FROM course_campus_assignments
                       WHERE user_id=? AND course_id IN
                             (SELECT id FROM courses WHERE program_id=?)""",
                    (roster["user_id"], program["id"]),
                )
                db.execute(
                    """DELETE FROM course_assignments
                       WHERE user_id=? AND course_id IN
                             (SELECT id FROM courses WHERE program_id=?)""",
                    (roster["user_id"], program["id"]),
                )
                db.executemany(
                    "INSERT INTO course_assignments(course_id,user_id) VALUES (?,?)",
                    [(course_id, roster["user_id"]) for course_id in course_ids],
                )
                db.executemany(
                    """INSERT INTO course_campus_assignments
                       (course_id,user_id,campus) VALUES (?,?,?)""",
                    [
                        (course_id, roster["user_id"], campus)
                        for course_id, campus in course_campus_pairs
                    ],
                )
                identifiers = {approved_email}
                if roster["account_email"]:
                    identifiers.add(roster["account_email"].casefold())
                db.executemany(
                    "DELETE FROM login_attempts WHERE email=?",
                    [(identifier,) for identifier in identifiers],
                )
            audit(
                "update_invitation",
                "faculty_roster",
                roster_id,
                {
                    "approved_email_before": roster["approved_email"],
                    "approved_email_after": approved_email,
                    "course_campus_pairs_before": old_course_campus_pairs,
                    "course_ids_after": course_ids,
                    "course_campus_pairs_after": course_campus_pairs,
                    "linked_user_id": roster["user_id"],
                    "active_account_synced": bool(roster["user_id"]),
                    "owner_approved": True,
                },
            )
        flash(
            f"Invitation and course-campus access updated for {display_name}.",
            "success",
        )
    except (ValueError, sqlite3.IntegrityError) as error:
        flash_validation(error)
    return redirect(url_for("platform.utrgv_faculty"))


@bp.post("/utrgv/faculty/<int:roster_id>/activate")
@role_required("admin")
def utrgv_faculty_activate(roster_id: int):
    if current_app.config["EDITION"] != "utrgv_mece":
        abort(404)
    program = require_program(edit=True)
    db = get_db()
    roster = db.execute(
        "SELECT * FROM faculty_roster WHERE id=? AND program_id=?", (roster_id, program["id"])
    ).fetchone()
    if not roster:
        abort(404)
    if roster["user_id"] or roster["status"] != "pending":
        abort(400, "Only a pending faculty invitation can be activated.")
    try:
        email = _normalize_utrgv_email(roster["approved_email"])
    except ValueError as error:
        abort(400, str(error))
    assigned_pairs = db.execute(
        """SELECT COUNT(*) FROM faculty_roster_course_campuses frcc
           JOIN faculty_roster fr ON fr.id=frcc.faculty_roster_id
           JOIN courses c ON c.id=frcc.course_id AND c.program_id=fr.program_id
           WHERE frcc.faculty_roster_id=? AND fr.program_id=?""",
        (roster_id, program["id"]),
    ).fetchone()[0]
    if not assigned_pairs:
        abort(
            400,
            "Assign at least one course and campus before activating this invitation.",
        )
    username = request.form.get("username", "").strip()
    password = request.form.get("temporary_password", "")
    if not username or len(password) < 12:
        flash("Provide a sign-in name and temporary password of at least 12 characters.", "error")
        return redirect(url_for("platform.utrgv_faculty"))
    try:
        with db:
            if db.execute("SELECT 1 FROM users WHERE email=? OR username=?", (email, username)).fetchone():
                raise ValueError("That email or sign-in name is already in use.")
            user_id = db.execute(
                """INSERT INTO users(email,username,full_name,password_hash,must_change_password)
                   VALUES (?,?,?,?,1)""",
                (email, username, roster["display_name"], generate_password_hash(password)),
            ).lastrowid
            db.execute(
                "INSERT INTO memberships(user_id,organization_id,role) VALUES (?,?,'faculty')",
                (user_id, session["organization_id"]),
            )
            db.execute(
                "INSERT INTO program_members(program_id,user_id,access_level) VALUES (?,?,'editor')",
                (program["id"], user_id),
            )
            db.execute(
                """INSERT INTO course_assignments(course_id,user_id)
                   SELECT DISTINCT frcc.course_id,?
                     FROM faculty_roster_course_campuses frcc
                     JOIN faculty_roster fr ON fr.id=frcc.faculty_roster_id
                     JOIN courses c ON c.id=frcc.course_id
                                   AND c.program_id=fr.program_id
                    WHERE frcc.faculty_roster_id=? AND fr.program_id=?""",
                (user_id, roster_id, program["id"]),
            )
            db.execute(
                """INSERT INTO course_campus_assignments(course_id,user_id,campus)
                   SELECT frcc.course_id,?,frcc.campus
                     FROM faculty_roster_course_campuses frcc
                     JOIN faculty_roster fr ON fr.id=frcc.faculty_roster_id
                     JOIN courses c ON c.id=frcc.course_id
                                   AND c.program_id=fr.program_id
                    WHERE frcc.faculty_roster_id=? AND fr.program_id=?""",
                (user_id, roster_id, program["id"]),
            )
            db.execute(
                "UPDATE faculty_roster SET user_id=?,status='active' WHERE id=?", (user_id, roster_id)
            )
            audit(
                "activate",
                "faculty_roster",
                roster_id,
                {
                    "user_id": user_id,
                    "approved_email": email,
                    "role": "faculty",
                    "course_campus_pair_count": assigned_pairs,
                },
            )
        flash(f"{roster['display_name']} can now sign in and must replace the temporary password.", "success")
    except (ValueError, sqlite3.IntegrityError) as error:
        flash_validation(error)
    return redirect(url_for("platform.utrgv_faculty"))
