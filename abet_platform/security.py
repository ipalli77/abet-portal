"""Authentication, authorization, CSRF, and audit helpers."""

from __future__ import annotations

import functools
import hmac
import json
import secrets
from typing import Callable

from flask import abort, current_app, flash, g, redirect, request, session, url_for

from .db import get_db


ROLE_RANK = {"reviewer": 10, "faculty": 20, "coordinator": 30, "admin": 40, "owner": 50}
UTRGV_CAMPUSES = ("Edinburg", "Brownsville")


def faculty_preview_scope_state(db, program_id: int, user_id: int) -> dict:
    """Return a fail-closed summary of every stored support-account scope row.

    The support identity is valid only when both authorization tables describe
    the same single active course and its campus rows are canonical.  Reading
    all rows before validating is important: an orphan, inactive-course, or
    otherwise malformed row must invalidate the profile instead of being
    silently filtered out and later authorizing evidence through a different
    SQL path.
    """
    # One statement gives both row detail and validation aggregates from the
    # same SQLite snapshot.  A second signed-in browser can switch scope, but
    # it cannot make us combine old pair rows with new course assignments.
    pair_rows = db.execute(
        """WITH support_pairs AS (
                   SELECT c.id AS course_id,c.code,c.is_active,cca.campus
                     FROM course_campus_assignments cca
                     JOIN courses c ON c.id=cca.course_id
                    WHERE cca.user_id=? AND c.program_id=?
               ),
               support_assignments AS (
                   SELECT c.id AS course_id,c.is_active
                     FROM course_assignments ca
                     JOIN courses c ON c.id=ca.course_id
                    WHERE ca.user_id=? AND c.program_id=?
               )
               SELECT support_pairs.*,
                      (SELECT COUNT(*) FROM support_pairs) AS pair_count,
                      (SELECT COUNT(DISTINCT course_id)
                         FROM support_pairs) AS pair_course_count,
                      (SELECT COUNT(*) FROM support_assignments)
                          AS assignment_count,
                      (SELECT MIN(course_id) FROM support_assignments)
                          AS assignment_course_id,
                      (SELECT COUNT(*) FROM support_assignments
                        WHERE is_active<>1) AS inactive_assignment_count
                 FROM support_pairs
                ORDER BY code,
                         CASE campus WHEN 'Edinburg' THEN 1
                                     WHEN 'Brownsville' THEN 2 ELSE 3 END,
                         campus""",
        (user_id, program_id, user_id, program_id),
    ).fetchall()
    pair_course_ids = {row["course_id"] for row in pair_rows}
    pair_count = pair_rows[0]["pair_count"] if pair_rows else 0
    pair_course_count = pair_rows[0]["pair_course_count"] if pair_rows else 0
    assignment_count = pair_rows[0]["assignment_count"] if pair_rows else 0
    assignment_course_id = (
        pair_rows[0]["assignment_course_id"] if pair_rows else None
    )
    inactive_assignment_count = (
        pair_rows[0]["inactive_assignment_count"] if pair_rows else 0
    )
    valid = (
        pair_count == len(pair_rows)
        and 1 <= pair_count <= len(UTRGV_CAMPUSES)
        and pair_course_count == 1
        and len(pair_course_ids) == 1
        and all(row["is_active"] for row in pair_rows)
        and all(row["campus"] in UTRGV_CAMPUSES for row in pair_rows)
        and assignment_count == 1
        and assignment_course_id in pair_course_ids
        and inactive_assignment_count == 0
    )
    campuses = tuple(row["campus"] for row in pair_rows) if valid else tuple()
    return {
        "has_valid_scope": valid,
        "course_id": pair_rows[0]["course_id"] if valid else None,
        "course_code": pair_rows[0]["code"] if valid else None,
        "campuses": campuses,
        "pairs": [
            (row["course_id"], row["campus"])
            for row in pair_rows
        ],
        "scope_summary": (
            f"{pair_rows[0]['code']} — {', '.join(campuses)}"
            if valid
            else "No faculty-view scope selected"
        ),
    }


def load_identity() -> None:
    g.user = None
    g.membership = None
    user_id = session.get("user_id")
    org_id = session.get("organization_id")
    if not user_id:
        return
    g.user = get_db().execute(
        "SELECT id, email, username, full_name, is_active, must_change_password FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    if not g.user or not g.user["is_active"]:
        session.clear()
        g.user = None
        return
    if org_id:
        g.membership = get_db().execute(
            "SELECT role FROM memberships WHERE user_id = ? AND organization_id = ?",
            (user_id, org_id),
        ).fetchone()
    if (
        current_app.config.get("EDITION") == "utrgv_mece"
        and g.membership
        and session.get("program_id")
    ):
        marker = get_db().execute(
            """SELECT pm.access_level
                 FROM program_support_accounts psa
                 JOIN programs p ON p.id=psa.program_id
                 LEFT JOIN program_members pm ON pm.program_id=psa.program_id
                                             AND pm.user_id=psa.user_id
                WHERE psa.program_id=? AND psa.user_id=?
                  AND p.organization_id=?""",
            (session["program_id"], user_id, org_id),
        ).fetchone()
        if marker and (
            g.membership["role"] != "faculty"
            or marker["access_level"] != "editor"
        ):
            # Even a corrupted marker must never elevate this dedicated
            # credential into an owner/administrator or manager identity.
            session.clear()
            g.user = None
            g.membership = None


def load_faculty_preview() -> None:
    """Expose only a valid, explicitly marked UTRGV faculty-view identity."""
    g.faculty_preview = None
    if (
        current_app.config.get("EDITION") != "utrgv_mece"
        or not getattr(g, "user", None)
        or not getattr(g, "membership", None)
        or not session.get("program_id")
        or not session.get("organization_id")
    ):
        return
    db = get_db()
    profile = db.execute(
        """SELECT psa.program_id,psa.user_id,psa.created_at,psa.updated_at,
                  u.email,u.username,u.full_name,u.is_active
             FROM program_support_accounts psa
             JOIN programs p ON p.id=psa.program_id
             JOIN users u ON u.id=psa.user_id AND u.is_active=1
             JOIN memberships m ON m.user_id=psa.user_id
                               AND m.organization_id=p.organization_id
                               AND m.role='faculty'
             JOIN program_members pm ON pm.program_id=psa.program_id
                                    AND pm.user_id=psa.user_id
                                    AND pm.access_level='editor'
            WHERE psa.program_id=? AND psa.user_id=?
              AND p.organization_id=? AND p.is_active=1""",
        (
            session["program_id"],
            g.user["id"],
            session["organization_id"],
        ),
    ).fetchone()
    if not profile:
        return
    scope = faculty_preview_scope_state(
        db, profile["program_id"], profile["user_id"]
    )
    item = dict(profile)
    item.update(scope)
    item["write_warning"] = (
        "Faculty-view mode uses real program data. Any records entered or "
        "changed are saved and permanently audited."
    )
    g.faculty_preview = item


def login_required(view: Callable) -> Callable:
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("platform.login", next=request.full_path))
        if g.membership is None:
            session.clear()
            return redirect(url_for("platform.login"))
        return view(*args, **kwargs)

    return wrapped


def role_required(minimum_role: str) -> Callable:
    def decorator(view: Callable) -> Callable:
        @functools.wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            current = ROLE_RANK.get(g.membership["role"], 0)
            if current < ROLE_RANK[minimum_role]:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def protect_csrf() -> None:
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return
    expected = session.get("csrf_token", "")
    supplied = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
    if not expected or not hmac.compare_digest(expected, supplied):
        abort(400, "Your form session expired. Refresh the page and try again.")


def enforce_password_change() -> None:
    """Keep temporary-password accounts inside the password-change flow."""
    if not getattr(g, "user", None) or not g.user["must_change_password"]:
        return
    allowed = {"platform.change_password", "platform.logout", "static", "platform.health"}
    if request.endpoint not in allowed:
        return redirect(url_for("platform.change_password"))


def require_program(program_id: int | None = None, *, edit: bool = False):
    """Return a tenant-scoped program or abort. Faculty must be assigned to it."""
    selected = program_id or session.get("program_id")
    if not selected:
        abort(404, "No program selected")
    row = get_db().execute(
        "SELECT * FROM programs WHERE id = ? AND organization_id = ? AND is_active = 1",
        (selected, session["organization_id"]),
    ).fetchone()
    if not row:
        abort(404)
    role = g.membership["role"]
    if edit and role == "reviewer":
        abort(403)
    if role in {"faculty", "reviewer"}:
        access = get_db().execute(
            "SELECT access_level FROM program_members WHERE program_id = ? AND user_id = ?",
            (row["id"], g.user["id"]),
        ).fetchone()
        if not access or (edit and access["access_level"] == "viewer"):
            abort(403)
    return row


def audit(action: str, entity_type: str, entity_id=None, details: dict | None = None) -> None:
    get_db().execute(
        """INSERT INTO audit_events
           (organization_id, user_id, action, entity_type, entity_id, details_json, ip_address)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            session["organization_id"],
            g.user["id"] if g.user else None,
            action,
            entity_type,
            str(entity_id) if entity_id is not None else None,
            json.dumps(details or {}, separators=(",", ":")),
            request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip(),
        ),
    )


def safe_next_url(value: str | None) -> str | None:
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return None


def parse_int(value, *, minimum: int | None = None) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise ValueError("A whole number is required.") from None
    if minimum is not None and result < minimum:
        raise ValueError(f"The value must be at least {minimum}.")
    return result


def parse_percent(value) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError("A percentage is required.") from None
    if not 0 <= result <= 100:
        raise ValueError("Percentages must be between 0 and 100.")
    return result


def flash_validation(error: Exception) -> None:
    flash(str(error), "error")
