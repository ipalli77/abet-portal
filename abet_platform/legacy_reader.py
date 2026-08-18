"""Read records produced by the original UTRGV ABET application safely.

This module deliberately has no Flask dependencies.  A route or command must pass
the configured database path to each function, which keeps tenant authorization in
the calling layer and makes the reader straightforward to test.

Legacy databases are always opened using SQLite's URI ``mode=ro`` and are also put
in ``query_only`` mode as defense in depth.  No function in this module creates,
migrates, attaches, or otherwise modifies a database.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Sequence

REQUIRED_COLUMNS = frozenset(
    {
        "id",
        "course",
        "course_name",
        "slo",
        "pi",
        "assessment_tool",
        "explanation",
        "semester",
        "blooms_level",
        "expert",
        "practitioner",
        "apprentice",
        "novice",
        "observations",
    }
)

RECORD_COLUMNS = (
    "id",
    "course",
    "course_name",
    "slo",
    "pi",
    "assessment_tool",
    "explanation",
    "semester",
    "blooms_level",
    "expert",
    "practitioner",
    "apprentice",
    "novice",
    "observations",
)

FILTER_COLUMNS = frozenset({"course", "semester", "slo"})
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
MAX_PAGE = 1_000_000
MAX_SEARCH_LENGTH = 200


class LegacyReaderError(ValueError):
    """Base error for an unavailable or incompatible legacy data source."""


class LegacySourceError(LegacyReaderError):
    """Raised when the configured source path cannot be read safely."""


class LegacySchemaError(LegacyReaderError):
    """Raised when a SQLite file is missing the expected legacy schema."""


def _coerce_positive_int(value: int, *, name: str, maximum: int | None = None) -> int:
    """Validate pagination values without silently accepting booleans or strings."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be no greater than {maximum}")
    return value


def _clean_filter(value: str | None, *, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must be text")
    value = value.strip()
    if not value:
        return None
    if len(value) > MAX_SEARCH_LENGTH:
        raise ValueError(f"{name} must be {MAX_SEARCH_LENGTH} characters or fewer")
    return value


def _resolve_source(source: str | Path) -> Path:
    if isinstance(source, Path):
        path = source.expanduser()
    elif isinstance(source, str) and source.strip():
        path = Path(source).expanduser()
    else:
        raise LegacySourceError("A legacy database path is required")

    try:
        path = path.resolve(strict=True)
    except (FileNotFoundError, OSError, ValueError) as error:
        raise LegacySourceError("The configured legacy database does not exist") from error
    if not path.is_file():
        raise LegacySourceError("The configured legacy database is not a regular file")
    return path


def validate_source(source: str | Path) -> Path:
    """Return the resolved source path after validating its file and schema.

    The returned path is suitable for display-independent internal use.  Do not
    show it to end users; :func:`source_metadata` intentionally omits it.
    """
    path = _resolve_source(source)

    with _open_database(path) as connection:
        _validate_schema(connection)
    return path


@contextmanager
def _open_database(source: Path) -> Iterator[sqlite3.Connection]:
    """Open *source* read-only and close it at the end of the context."""
    # Path.as_uri percent-encodes URI metacharacters in filenames, preventing a
    # configured path from injecting SQLite URI parameters such as ``mode=rw``.
    uri = f"{source.as_uri()}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=5.0)
    except sqlite3.Error as error:
        raise LegacySourceError("The configured legacy database could not be opened") from error
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA trusted_schema = OFF")
        connection.execute("PRAGMA busy_timeout = 5000")
        yield connection
    except sqlite3.DatabaseError as error:
        raise LegacySourceError("The configured legacy database could not be read") from error
    finally:
        connection.close()


def _validate_schema(connection: sqlite3.Connection) -> None:
    table = connection.execute(
        "SELECT type FROM sqlite_master WHERE name = ? COLLATE NOCASE",
        ("abet_entries",),
    ).fetchone()
    if table is None or table["type"] != "table":
        raise LegacySchemaError("The database does not contain the required abet_entries table")

    # The table name is a module constant, not user input.
    table_columns = connection.execute("PRAGMA table_info(abet_entries)").fetchall()
    columns = {row["name"].lower() for row in table_columns}
    missing = sorted(REQUIRED_COLUMNS - columns)
    if missing:
        raise LegacySchemaError(f"The abet_entries table is missing required columns: {', '.join(missing)}")

    id_column = next(row for row in table_columns if row["name"].lower() == "id")
    if not id_column["pk"]:
        raise LegacySchemaError("The abet_entries.id column must be a primary key")


@contextmanager
def _validated_connection(source: str | Path) -> Iterator[tuple[Path, sqlite3.Connection]]:
    path = _resolve_source(source)
    with _open_database(path) as connection:
        _validate_schema(connection)
        yield path, connection


def _where_clause(
    *,
    course: str | None = None,
    semester: str | None = None,
    slo: str | None = None,
    search: str | None = None,
) -> tuple[str, list[str]]:
    filters = {
        "course": _clean_filter(course, name="course"),
        "semester": _clean_filter(semester, name="semester"),
        "slo": _clean_filter(slo, name="slo"),
    }
    predicates: list[str] = []
    parameters: list[str] = []
    for column, value in filters.items():
        if value is not None:
            # Column names come exclusively from this module's allowlist.
            if column not in FILTER_COLUMNS:  # pragma: no cover - defensive invariant
                raise ValueError("Unsupported legacy record filter")
            predicates.append(f"TRIM({column}) = ? COLLATE NOCASE")
            parameters.append(value)

    search = _clean_filter(search, name="search")
    if search is not None:
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        searchable = ("course", "course_name", "slo", "pi", "assessment_tool", "semester", "observations")
        predicates.append("(" + " OR ".join(f"COALESCE({column}, '') LIKE ? ESCAPE '\\'" for column in searchable) + ")")
        parameters.extend([pattern] * len(searchable))

    return (" WHERE " + " AND ".join(predicates) if predicates else ""), parameters


def source_metadata(source: str | Path) -> dict[str, object]:
    """Return non-sensitive source details and a content fingerprint.

    The absolute source path is deliberately excluded because it may reveal server
    layout or account names in an administrator-facing page.
    """
    path = validate_source(source)
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        stat = path.stat()
    except OSError as error:
        raise LegacySourceError("The configured legacy database could not be fingerprinted") from error
    return {
        "filename": path.name,
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "sha256": digest.hexdigest(),
    }


def summarize_records(
    source: str | Path,
    *,
    course: str | None = None,
    semester: str | None = None,
    slo: str | None = None,
    search: str | None = None,
) -> dict[str, object]:
    """Summarize the matching legacy records for an authorized tenant admin."""
    where, parameters = _where_clause(course=course, semester=semester, slo=slo, search=search)
    with _validated_connection(source) as (_, connection):
        row = connection.execute(
            f"""SELECT COUNT(*) AS record_count,
                       COUNT(DISTINCT NULLIF(TRIM(course), '')) AS course_count,
                       COUNT(DISTINCT NULLIF(TRIM(semester), '')) AS semester_count,
                       COUNT(DISTINCT NULLIF(TRIM(slo), '')) AS outcome_count,
                       SUM(CASE WHEN NULLIF(TRIM(observations), '') IS NOT NULL THEN 1 ELSE 0 END)
                           AS records_with_observations,
                       AVG(COALESCE(expert, 0) + COALESCE(practitioner, 0)) AS average_attainment
                FROM abet_entries{where}""",
            parameters,
        ).fetchone()
        return {
            "record_count": int(row["record_count"]),
            "course_count": int(row["course_count"]),
            "semester_count": int(row["semester_count"]),
            "outcome_count": int(row["outcome_count"]),
            "records_with_observations": int(row["records_with_observations"] or 0),
            "average_attainment": round(float(row["average_attainment"]), 1)
            if row["average_attainment"] is not None
            else None,
        }


def filter_options(source: str | Path) -> dict[str, list[str]]:
    """Return distinct, display-ready values for legacy record filters."""
    with _validated_connection(source) as (_, connection):
        options: dict[str, list[str]] = {}
        for column in ("course", "semester", "slo"):
            # Column names are fixed above and cannot originate in a request.
            rows = connection.execute(
                f"""SELECT DISTINCT TRIM({column}) AS value
                    FROM abet_entries
                    WHERE NULLIF(TRIM({column}), '') IS NOT NULL
                    ORDER BY value COLLATE NOCASE"""
            ).fetchall()
            options[column] = [row["value"] for row in rows]
        return options


def list_records(
    source: str | Path,
    *,
    course: str | None = None,
    semester: str | None = None,
    slo: str | None = None,
    search: str | None = None,
    page: int = 1,
    per_page: int = DEFAULT_PAGE_SIZE,
) -> dict[str, object]:
    """Return matching legacy records with bounded, deterministic pagination."""
    page = _coerce_positive_int(page, name="page", maximum=MAX_PAGE)
    per_page = _coerce_positive_int(per_page, name="per_page", maximum=MAX_PAGE_SIZE)
    where, parameters = _where_clause(course=course, semester=semester, slo=slo, search=search)
    offset = (page - 1) * per_page

    with _validated_connection(source) as (_, connection):
        total = int(connection.execute(f"SELECT COUNT(*) FROM abet_entries{where}", parameters).fetchone()[0])
        selected = ", ".join(RECORD_COLUMNS)
        rows = connection.execute(
            f"SELECT {selected} FROM abet_entries{where} ORDER BY id DESC LIMIT ? OFFSET ?",
            [*parameters, per_page, offset],
        ).fetchall()

    pages = (total + per_page - 1) // per_page
    return {
        "records": [dict(row) for row in rows],
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": pages,
        "has_previous": page > 1,
        "has_next": page < pages,
    }


def list_drafts(source: str | Path) -> list[dict[str, object]]:
    """Return separately labeled, unsent legacy drafts when that optional table exists."""
    with _validated_connection(source) as (_, connection):
        table = connection.execute(
            "SELECT type FROM sqlite_master WHERE name='user_drafts' COLLATE NOCASE"
        ).fetchone()
        if not table or table["type"] != "table":
            return []
        columns = {row["name"].lower() for row in connection.execute("PRAGMA table_info(user_drafts)")}
        if not {"user", "blob"}.issubset(columns):
            raise LegacySchemaError("The optional user_drafts table has an incompatible schema")
        drafts: list[dict[str, object]] = []
        for row in connection.execute("SELECT user,blob FROM user_drafts ORDER BY user"):
            blob = row["blob"] or "[]"
            if len(blob) > 5_000_000:
                raise LegacySchemaError("A legacy draft exceeds the safe review limit")
            try:
                parsed = json.loads(blob)
            except json.JSONDecodeError as error:
                raise LegacySchemaError("A legacy draft contains invalid JSON") from error
            if not isinstance(parsed, list):
                raise LegacySchemaError("A legacy draft must contain a list of records")
            drafts.append({"user": row["user"], "rows": parsed[:1000], "row_count": len(parsed)})
        return drafts


__all__: Sequence[str] = (
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE",
    "MAX_PAGE_SIZE",
    "LegacyReaderError",
    "LegacySchemaError",
    "LegacySourceError",
    "filter_options",
    "list_records",
    "list_drafts",
    "source_metadata",
    "summarize_records",
    "validate_source",
)
