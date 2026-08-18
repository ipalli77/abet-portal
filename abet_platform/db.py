"""SQLite persistence helpers for the ABET platform."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from flask import current_app, g


def _make_assessment_sample_size_nullable(connection: sqlite3.Connection) -> None:
    """Rebuild the assessment table once so percentage records need no sample size.

    SQLite cannot remove a ``NOT NULL`` constraint in place.  The rebuild keeps
    primary keys intact, runs with foreign-key actions temporarily disabled, and
    validates every retained relationship before returning.
    """
    columns = {
        row["name"]: row for row in connection.execute("PRAGMA table_info(assessment_records)")
    }
    sample_size = columns.get("sample_size")
    if not sample_size or not sample_size["notnull"]:
        return

    connection.commit()
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        connection.executescript(
            """
            BEGIN IMMEDIATE;
            CREATE TABLE assessment_records_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                program_id INTEGER NOT NULL REFERENCES programs(id) ON DELETE CASCADE,
                term_id INTEGER NOT NULL REFERENCES academic_terms(id),
                course_id INTEGER NOT NULL REFERENCES courses(id),
                outcome_id INTEGER NOT NULL REFERENCES outcomes(id),
                indicator_id INTEGER NOT NULL REFERENCES performance_indicators(id),
                rubric_id INTEGER NOT NULL REFERENCES rubrics(id),
                collected_by INTEGER NOT NULL REFERENCES users(id),
                approved_by INTEGER REFERENCES users(id),
                campus TEXT NOT NULL DEFAULT 'Unassigned'
                    CHECK (campus IN ('Edinburg', 'Brownsville', 'Unassigned')),
                method TEXT NOT NULL DEFAULT 'direct' CHECK (method IN ('direct', 'indirect')),
                assessment_tool TEXT NOT NULL,
                bloom_level TEXT NOT NULL DEFAULT '',
                sample_size INTEGER CHECK (sample_size IS NULL OR sample_size > 0),
                result_basis TEXT NOT NULL DEFAULT 'student_counts'
                    CHECK (result_basis IN ('student_counts', 'percentages')),
                target REAL NOT NULL CHECK (target BETWEEN 0 AND 100),
                rationale TEXT NOT NULL DEFAULT '',
                observations TEXT NOT NULL DEFAULT '',
                action_notes TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft', 'submitted', 'approved', 'returned')),
                submitted_at TEXT,
                approved_at TEXT,
                record_version INTEGER NOT NULL DEFAULT 1 CHECK (record_version > 0),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO assessment_records_new
                (id,program_id,term_id,course_id,outcome_id,indicator_id,rubric_id,
                 collected_by,approved_by,campus,method,assessment_tool,bloom_level,
                 sample_size,result_basis,target,rationale,observations,action_notes,
                 status,submitted_at,approved_at,record_version,created_at,updated_at)
            SELECT id,program_id,term_id,course_id,outcome_id,indicator_id,rubric_id,
                   collected_by,approved_by,campus,method,assessment_tool,bloom_level,
                   sample_size,result_basis,target,rationale,observations,action_notes,
                   status,submitted_at,approved_at,record_version,created_at,updated_at
              FROM assessment_records;
            DROP TABLE assessment_records;
            ALTER TABLE assessment_records_new RENAME TO assessment_records;
            CREATE INDEX idx_assessments_program
                ON assessment_records(program_id, status, term_id);
            CREATE INDEX idx_assessments_dimensions
                ON assessment_records(outcome_id, indicator_id, course_id);
            CREATE INDEX idx_assessments_campus
                ON assessment_records(program_id, campus, status, term_id);
            COMMIT;
            """
        )
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise sqlite3.IntegrityError(
                "Assessment migration retained invalid foreign-key references."
            )
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.execute("PRAGMA foreign_keys = ON")


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        db_path = Path(current_app.config["DATABASE"])
        db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        g.db = connection
    return g.db


def close_db(_error: BaseException | None = None) -> None:
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def init_db() -> None:
    schema_path = Path(__file__).with_name("schema.sql")
    connection = get_db()
    connection.executescript(schema_path.read_text(encoding="utf-8"))
    installed_versions = {
        row["version"] for row in connection.execute("SELECT version FROM schema_versions")
    }
    # Lightweight forward migration for databases created by version 0.1.
    user_columns = {row["name"] for row in connection.execute("PRAGMA table_info(users)")}
    if "username" not in user_columns:
        connection.execute("ALTER TABLE users ADD COLUMN username TEXT")
    if "must_change_password" not in user_columns:
        connection.execute(
            "ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0 CHECK (must_change_password IN (0, 1))"
        )
    faculty_roster_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(faculty_roster)")
    }
    if "approved_email" not in faculty_roster_columns:
        connection.execute(
            "ALTER TABLE faculty_roster ADD COLUMN approved_email TEXT COLLATE NOCASE"
        )
    assessment_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(assessment_records)")
    }
    if "campus" not in assessment_columns:
        # Existing UTRGV records predate campus collection.  Preserve them as
        # explicitly unresolved; an administrator must map the source before
        # they can enter the approval workflow or campus comparisons.
        connection.execute(
            """ALTER TABLE assessment_records ADD COLUMN campus TEXT NOT NULL
               DEFAULT 'Unassigned'
               CHECK (campus IN ('Edinburg', 'Brownsville', 'Unassigned'))"""
        )
    if "record_version" not in assessment_columns:
        connection.execute(
            """ALTER TABLE assessment_records ADD COLUMN record_version INTEGER
               NOT NULL DEFAULT 1 CHECK (record_version > 0)"""
        )
    if "result_basis" not in assessment_columns:
        connection.execute(
            """ALTER TABLE assessment_records ADD COLUMN result_basis TEXT NOT NULL
               DEFAULT 'student_counts'
               CHECK (result_basis IN ('student_counts', 'percentages'))"""
        )
    result_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(assessment_results)")
    }
    if "level_percent" not in result_columns:
        connection.execute(
            """ALTER TABLE assessment_results ADD COLUMN level_percent REAL
               CHECK (level_percent IS NULL OR level_percent BETWEEN 0 AND 100)"""
        )
    _make_assessment_sample_size_nullable(connection)
    legacy_columns = {row["name"] for row in connection.execute("PRAGMA table_info(legacy_import_items)")}
    for column in ("expert_percent", "practitioner_percent", "apprentice_percent", "novice_percent"):
        if column not in legacy_columns:
            connection.execute(f"ALTER TABLE legacy_import_items ADD COLUMN {column} REAL NOT NULL DEFAULT 0")
    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username) WHERE username IS NOT NULL")
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_legacy_import_assessment ON legacy_import_items(assessment_id)"
    )
    connection.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_faculty_roster_approved_email
           ON faculty_roster(program_id, approved_email)
           WHERE approved_email IS NOT NULL"""
    )
    connection.execute(
        """CREATE INDEX IF NOT EXISTS idx_assessments_campus
           ON assessment_records(program_id, campus, status, term_id)"""
    )
    # One-time customer-confirmed migration: source records already present in
    # the existing UTRGV workspace belong to Edinburg. Version gating is
    # deliberate; a source imported later must retain its explicitly selected
    # campus and can never be silently classified on a future restart.
    if (
        current_app.config.get("EDITION") == "utrgv_mece"
        and 5 not in installed_versions
    ):
        connection.execute(
            """UPDATE assessment_records AS ar SET campus='Edinburg'
               WHERE ar.campus='Unassigned'
                 AND EXISTS (
                     SELECT 1 FROM legacy_import_items li
                      WHERE li.assessment_id=ar.id AND li.program_id=ar.program_id
                 )"""
        )
        connection.execute(
            """INSERT INTO assessment_revisions
               (program_id,assessment_id,changed_by,changed_by_name,change_note,
                before_json,after_json)
               SELECT ar.program_id,ar.id,NULL,'UTRGV data administrator',
                      'Current source campus confirmed as Edinburg.',
                      '{"campus":"not recorded"}',
                      '{"campus":"Edinburg"}'
                 FROM assessment_records ar
                 JOIN legacy_import_items li ON li.assessment_id=ar.id
                                        AND li.program_id=ar.program_id
                WHERE ar.campus='Edinburg'
                  AND NOT EXISTS (
                      SELECT 1 FROM assessment_revisions rv
                       WHERE rv.assessment_id=ar.id
                         AND rv.program_id=ar.program_id
                  )"""
        )
        organization_rows = connection.execute(
            """SELECT p.organization_id, COUNT(*) AS changed_count
                 FROM assessment_records ar
                 JOIN programs p ON p.id=ar.program_id
                 JOIN legacy_import_items li ON li.assessment_id=ar.id
                                            AND li.program_id=ar.program_id
                WHERE ar.campus='Edinburg'
                GROUP BY p.organization_id"""
        ).fetchall()
        connection.executemany(
            """INSERT INTO audit_events
               (organization_id,user_id,action,entity_type,entity_id,details_json)
               VALUES (?,NULL,'campus_confirmation','assessment_batch',NULL,?)""",
            [
                (
                    row["organization_id"],
                    '{"administrative_change":true,"campus":"Edinburg",'
                    f'"records_confirmed":{row["changed_count"]}}}',
                )
                for row in organization_rows
            ],
        )
    connection.execute("INSERT OR IGNORE INTO schema_versions(version) VALUES (2)")
    connection.execute("INSERT OR IGNORE INTO schema_versions(version) VALUES (3)")
    connection.execute("INSERT OR IGNORE INTO schema_versions(version) VALUES (4)")
    connection.execute("INSERT OR IGNORE INTO schema_versions(version) VALUES (8)")
    if current_app.config.get("EDITION") == "utrgv_mece":
        if 10 not in installed_versions:
            from .utrgv_config import (
                FACULTY_ROSTER,
                ORGANIZATION_NAME,
                OWNER_EMAIL,
                PROGRAM_CODE,
                seed_utrgv_faculty_roster,
            )

            programs = connection.execute(
                """SELECT p.id,p.organization_id FROM programs p
                   JOIN organizations o ON o.id=p.organization_id
                   WHERE p.code=? AND o.name=? ORDER BY p.id""",
                (PROGRAM_CODE, ORGANIZATION_NAME),
            ).fetchall()
            for program in programs:
                seed_utrgv_faculty_roster(connection, program["id"])
                connection.execute(
                    """INSERT INTO audit_events
                       (organization_id,user_id,action,entity_type,entity_id,details_json)
                       SELECT ?,NULL,'faculty_roster_configuration','faculty_roster',?,?
                       WHERE NOT EXISTS (
                           SELECT 1 FROM audit_events
                           WHERE organization_id=?
                             AND action='faculty_roster_configuration'
                             AND entity_type='faculty_roster'
                             AND entity_id=?
                       )""",
                    (
                        program["organization_id"],
                        str(program["id"]),
                        json.dumps(
                            {
                                "approved_faculty": len(FACULTY_ROSTER),
                                "course_assignments": sum(
                                    len(entry.course_codes) for entry in FACULTY_ROSTER
                                ),
                                "designated_owner": OWNER_EMAIL,
                                "migration_version": 10,
                                "account_credentials_changed": False,
                            },
                            separators=(",", ":"),
                        ),
                        program["organization_id"],
                        str(program["id"]),
                    ),
                )
        connection.execute("INSERT OR IGNORE INTO schema_versions(version) VALUES (10)")
        connection.execute("INSERT OR IGNORE INTO schema_versions(version) VALUES (5)")
        if 6 not in installed_versions:
            # Databases migrated by the first release of version 5 already
            # contain the per-record confirmation notes. Add the corresponding
            # batch audit entry once without changing any assessment data.
            confirmation_rows = connection.execute(
                """SELECT p.organization_id,COUNT(*) AS changed_count
                     FROM assessment_revisions rv
                     JOIN programs p ON p.id=rv.program_id
                    WHERE rv.changed_by IS NULL
                      AND rv.change_note='Current source campus confirmed as Edinburg.'
                      AND NOT EXISTS (
                          SELECT 1 FROM audit_events ae
                           WHERE ae.organization_id=p.organization_id
                             AND ae.action='campus_confirmation'
                             AND ae.entity_type='assessment_batch'
                      )
                    GROUP BY p.organization_id"""
            ).fetchall()
            connection.executemany(
                """INSERT INTO audit_events
                   (organization_id,user_id,action,entity_type,entity_id,details_json)
                   VALUES (?,NULL,'campus_confirmation','assessment_batch',NULL,?)""",
                [
                    (
                        row["organization_id"],
                        '{"administrative_change":true,"campus":"Edinburg",'
                        f'"records_confirmed":{row["changed_count"]}}}',
                    )
                    for row in confirmation_rows
                ],
            )
        if 7 not in installed_versions:
            current_source_note = (
                "Current source percentage distribution. Original sample size "
                "and collector were not stored."
            )
            terminology_note = (
                "Current-source terminology updated; assessment values were unchanged."
            )
            terminology_records = connection.execute(
                """SELECT ar.id,ar.program_id,p.organization_id,ar.status,ar.action_notes
                     FROM assessment_records ar
                     JOIN legacy_import_items li ON li.assessment_id=ar.id
                                                AND li.program_id=ar.program_id
                     JOIN programs p ON p.id=ar.program_id
                    WHERE ar.action_notes=
                          'Historical percentage distribution. Original sample size and collector were not stored.'"""
            ).fetchall()
            connection.executemany(
                """INSERT INTO assessment_revisions
                   (program_id,assessment_id,changed_by,changed_by_name,change_note,
                    before_json,after_json)
                   VALUES (?,?,NULL,'UTRGV data administrator',?,?,?)""",
                [
                    (
                        row["program_id"],
                        row["id"],
                        terminology_note,
                        json.dumps(
                            {"action_notes": row["action_notes"], "status": row["status"]},
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        json.dumps(
                            {"action_notes": current_source_note, "status": "draft"},
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    )
                    for row in terminology_records
                ],
            )
            connection.executemany(
                """UPDATE assessment_records
                   SET action_notes=?,status='draft',submitted_at=NULL,
                       approved_at=NULL,approved_by=NULL,
                       record_version=record_version+1,
                       updated_at=CURRENT_TIMESTAMP
                   WHERE id=? AND program_id=?""",
                [
                    (current_source_note, row["id"], row["program_id"])
                    for row in terminology_records
                ],
            )
            connection.execute(
                """UPDATE performance_indicators
                   SET description='Unmapped source PI — administrator review required'
                   WHERE code='UNMAPPED'
                     AND description='Unmapped legacy PI — coordinator review required'"""
            )
            if terminology_records:
                organization_counts: dict[int, int] = {}
                organization_review_resets: dict[int, int] = {}
                for row in terminology_records:
                    organization_id = row["organization_id"]
                    organization_counts[organization_id] = (
                        organization_counts.get(organization_id, 0) + 1
                    )
                    organization_review_resets[organization_id] = (
                        organization_review_resets.get(organization_id, 0)
                        + int(row["status"] in {"submitted", "approved"})
                    )
                connection.executemany(
                    """INSERT INTO audit_events
                       (organization_id,user_id,action,entity_type,entity_id,details_json)
                       VALUES (?,NULL,'source_terminology_update','assessment_batch',NULL,?)""",
                    [
                        (
                            organization_id,
                            json.dumps(
                                {
                                    "administrative_change": True,
                                    "records_changed": count,
                                    "review_reset": organization_review_resets[
                                        organization_id
                                    ],
                                },
                                separators=(",", ":"),
                            ),
                        )
                        for organization_id, count in organization_counts.items()
                    ],
                )
        connection.execute("INSERT OR IGNORE INTO schema_versions(version) VALUES (7)")
        if 9 not in installed_versions:
            # UTRGV faculty now enter the EPAN distribution directly as
            # percentages. Preserve all existing evidence by translating valid
            # count distributions and copying exact source percentages.
            connection.execute(
                """INSERT OR IGNORE INTO assessment_results
                   (assessment_id,rubric_level_id,student_count,level_percent)
                   SELECT ar.id,rl.id,0,
                          CASE LOWER(rl.label)
                              WHEN 'expert' THEN li.expert_percent
                              WHEN 'practitioner' THEN li.practitioner_percent
                              WHEN 'apprentice' THEN li.apprentice_percent
                              WHEN 'novice' THEN li.novice_percent
                          END
                     FROM legacy_import_items li
                     JOIN assessment_records ar ON ar.id=li.assessment_id
                                               AND ar.program_id=li.program_id
                     JOIN rubric_levels rl ON rl.rubric_id=ar.rubric_id
                    WHERE LOWER(rl.label) IN
                          ('expert','practitioner','apprentice','novice')"""
            )
            connection.execute(
                """UPDATE assessment_results AS rs
                   SET level_percent=(
                       SELECT CASE LOWER(rl.label)
                           WHEN 'expert' THEN li.expert_percent
                           WHEN 'practitioner' THEN li.practitioner_percent
                           WHEN 'apprentice' THEN li.apprentice_percent
                           WHEN 'novice' THEN li.novice_percent
                       END
                       FROM rubric_levels rl
                       JOIN assessment_records ar ON ar.id=rs.assessment_id
                       JOIN legacy_import_items li ON li.assessment_id=ar.id
                                                  AND li.program_id=ar.program_id
                       WHERE rl.id=rs.rubric_level_id
                   )
                   WHERE EXISTS (
                       SELECT 1 FROM assessment_records ar
                       JOIN legacy_import_items li ON li.assessment_id=ar.id
                                                  AND li.program_id=ar.program_id
                       WHERE ar.id=rs.assessment_id
                   )"""
            )
            connection.execute(
                """UPDATE assessment_results AS rs
                   SET level_percent=(
                       SELECT 100.0 * rs.student_count / totals.total_count
                       FROM (
                           SELECT assessment_id,SUM(student_count) AS total_count
                           FROM assessment_results GROUP BY assessment_id
                       ) totals
                       WHERE totals.assessment_id=rs.assessment_id
                         AND totals.total_count > 0
                   )
                   WHERE rs.level_percent IS NULL
                     AND EXISTS (
                         SELECT 1 FROM assessment_records ar
                         WHERE ar.id=rs.assessment_id
                     )"""
            )
            connection.execute(
                """UPDATE assessment_records
                   SET result_basis='percentages',sample_size=NULL
                   WHERE EXISTS (
                       SELECT 1 FROM assessment_results rs
                       WHERE rs.assessment_id=assessment_records.id
                       GROUP BY rs.assessment_id
                       HAVING COUNT(*)=SUM(rs.level_percent IS NOT NULL)
                          AND ABS(SUM(rs.level_percent)-100.0) <= 0.000001
                   )"""
            )
        connection.execute("INSERT OR IGNORE INTO schema_versions(version) VALUES (9)")
        if 11 not in installed_versions:
            # Earlier UTRGV releases authorized faculty by course only.  Give
            # every existing invitation and active assignment both campuses so
            # upgrading cannot unexpectedly remove access.  Subsequent owner
            # edits replace these rows with the requested exact pair scope.
            connection.execute(
                """INSERT OR IGNORE INTO faculty_roster_course_campuses
                   (faculty_roster_id,course_id,campus)
                   SELECT frc.faculty_roster_id,frc.course_id,campus.name
                     FROM faculty_roster_courses frc
                     JOIN faculty_roster fr ON fr.id=frc.faculty_roster_id
                     JOIN courses c ON c.id=frc.course_id
                                   AND c.program_id=fr.program_id
                     CROSS JOIN (
                         SELECT 'Edinburg' AS name
                         UNION ALL SELECT 'Brownsville'
                     ) campus"""
            )
            connection.execute(
                """INSERT OR IGNORE INTO course_campus_assignments
                   (course_id,user_id,campus)
                   SELECT ca.course_id,ca.user_id,campus.name
                     FROM course_assignments ca
                     JOIN courses c ON c.id=ca.course_id
                     JOIN program_members pm ON pm.program_id=c.program_id
                                            AND pm.user_id=ca.user_id
                     JOIN programs p ON p.id=c.program_id
                     JOIN memberships m ON m.user_id=ca.user_id
                                       AND m.organization_id=p.organization_id
                                       AND m.role IN ('faculty','reviewer')
                     CROSS JOIN (
                         SELECT 'Edinburg' AS name
                         UNION ALL SELECT 'Brownsville'
                     ) campus"""
            )
        connection.execute("INSERT OR IGNORE INTO schema_versions(version) VALUES (11)")
        # Version 12 introduces an explicit, owner-controlled faculty-view
        # support identity.  No account or credential is seeded automatically.
        connection.execute("INSERT OR IGNORE INTO schema_versions(version) VALUES (12)")
    connection.execute("INSERT OR IGNORE INTO schema_versions(version) VALUES (6)")
    connection.commit()


def init_app(app) -> None:
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()
