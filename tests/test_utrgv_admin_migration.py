from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from abet_platform import create_app
from abet_platform.db import get_db


class UtrgvAdministratorMigrationTests(unittest.TestCase):
    """Version 5 only confirms current-source rows as Edinburg, once."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.database = root / "utrgv.db"
        self.config = {
            "TESTING": True,
            "SECRET_KEY": "utrgv-admin-migration-secret",
            "DATABASE": str(self.database),
            "UPLOAD_FOLDER": str(root / "uploads"),
            "EDITION": "utrgv_mece",
            "PRODUCT_NAME": "UTRGV ME Accreditation Hub",
            "CUSTOMER_NAME": "UTRGV Department of Mechanical Engineering",
        }
        self.app = create_app(self.config)
        self.client = self.app.test_client()
        self._setup_workspace()

    def tearDown(self):
        self.temp.cleanup()

    def csrf(self) -> str:
        with self.client.session_transaction() as session:
            return session["csrf_token"]

    def _setup_workspace(self) -> None:
        self.client.get("/setup")
        response = self.client.post(
            "/setup",
            data={
                "csrf_token": self.csrf(),
                "full_name": "Accreditation Director",
                "email": "isaac.palli@utrgv.edu",
                "password": "owner-password-long",
            },
        )
        self.assertEqual(response.status_code, 302)

    @staticmethod
    def _insert_assessment(db, dimensions, *, campus: str, tool: str) -> int:
        return db.execute(
            """INSERT INTO assessment_records
               (program_id,term_id,course_id,outcome_id,indicator_id,rubric_id,
                collected_by,campus,method,assessment_tool,bloom_level,sample_size,
                target,status)
               VALUES (?,?,?,?,?,?,?,?,'direct',?,'Analyze',10000,70,'draft')""",
            (
                dimensions["program_id"],
                dimensions["term_id"],
                dimensions["course_id"],
                dimensions["outcome_id"],
                dimensions["indicator_id"],
                dimensions["rubric_id"],
                dimensions["user_id"],
                campus,
                tool,
            ),
        ).lastrowid

    def test_version_five_backfill_is_source_scoped_and_idempotent(self):
        with self.app.app_context():
            db = get_db()
            program_id = db.execute("SELECT id FROM programs WHERE code='BSME'").fetchone()[0]
            outcome_id = db.execute(
                "SELECT id FROM outcomes WHERE program_id=? ORDER BY display_order,id LIMIT 1",
                (program_id,),
            ).fetchone()[0]
            dimensions = {
                "program_id": program_id,
                "user_id": db.execute("SELECT id FROM users LIMIT 1").fetchone()[0],
                "term_id": db.execute(
                    "SELECT id FROM academic_terms WHERE program_id=? LIMIT 1",
                    (program_id,),
                ).fetchone()[0],
                "course_id": db.execute(
                    "SELECT id FROM courses WHERE program_id=? LIMIT 1",
                    (program_id,),
                ).fetchone()[0],
                "outcome_id": outcome_id,
                "indicator_id": db.execute(
                    "SELECT id FROM performance_indicators WHERE outcome_id=? LIMIT 1",
                    (outcome_id,),
                ).fetchone()[0],
                "rubric_id": db.execute(
                    "SELECT id FROM rubrics WHERE program_id=? LIMIT 1",
                    (program_id,),
                ).fetchone()[0],
            }
            current_source_id = self._insert_assessment(
                db,
                dimensions,
                campus="Unassigned",
                tool="Current source row without pre-version-five campus",
            )
            ordinary_id = self._insert_assessment(
                db,
                dimensions,
                campus="Unassigned",
                tool="Faculty row without a campus",
            )
            brownsville_source_id = self._insert_assessment(
                db,
                dimensions,
                campus="Brownsville",
                tool="Existing Brownsville source row",
            )
            db.executemany(
                """INSERT INTO legacy_import_items
                   (program_id,source_fingerprint,source_record_id,assessment_id,
                    expert_percent,practitioner_percent,apprentice_percent,novice_percent)
                   VALUES (?,?,?,?,40,30,20,10)""",
                (
                    (program_id, "current-edinburg", 1, current_source_id),
                    (program_id, "existing-brownsville", 1, brownsville_source_id),
                ),
            )
            db.execute("DELETE FROM schema_versions WHERE version=5")
            db.commit()

        migrated_app = create_app(self.config)
        with migrated_app.app_context():
            db = get_db()
            campuses = {
                row["id"]: row["campus"]
                for row in db.execute(
                    "SELECT id,campus FROM assessment_records WHERE id IN (?,?,?)",
                    (current_source_id, ordinary_id, brownsville_source_id),
                )
            }
            self.assertEqual(campuses[current_source_id], "Edinburg")
            self.assertEqual(campuses[ordinary_id], "Unassigned")
            self.assertEqual(campuses[brownsville_source_id], "Brownsville")
            revisions = db.execute(
                """SELECT assessment_id,changed_by,changed_by_name,change_note,
                          before_json,after_json
                   FROM assessment_revisions ORDER BY assessment_id"""
            ).fetchall()
            self.assertEqual(len(revisions), 1)
            self.assertEqual(revisions[0]["assessment_id"], current_source_id)
            self.assertIsNone(revisions[0]["changed_by"])
            self.assertEqual(revisions[0]["changed_by_name"], "UTRGV data administrator")
            self.assertEqual(
                revisions[0]["change_note"],
                "Current source campus confirmed as Edinburg.",
            )
            self.assertEqual(revisions[0]["before_json"], '{"campus":"not recorded"}')
            self.assertEqual(revisions[0]["after_json"], '{"campus":"Edinburg"}')
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM schema_versions WHERE version=5"
                ).fetchone()[0],
                1,
            )

        rerun_app = create_app(self.config)
        with rerun_app.app_context():
            db = get_db()
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM assessment_revisions").fetchone()[0],
                1,
            )
            self.assertEqual(
                db.execute(
                    "SELECT campus FROM assessment_records WHERE id=?",
                    (ordinary_id,),
                ).fetchone()[0],
                "Unassigned",
            )

    def test_generic_startup_does_not_consume_utrgv_migration_version(self):
        other_root = Path(self.temp.name) / "generic-first"
        generic_config = {
            **self.config,
            "DATABASE": str(other_root / "shared.db"),
            "UPLOAD_FOLDER": str(other_root / "uploads"),
            "EDITION": "generic",
            "PRODUCT_NAME": "AccreditationOS",
            "CUSTOMER_NAME": "",
        }
        generic_app = create_app(generic_config)
        generic_client = generic_app.test_client()
        generic_client.get("/setup")
        with generic_client.session_transaction() as session:
            token = session["csrf_token"]
        response = generic_client.post(
            "/setup",
            data={
                "csrf_token": token,
                "institution": "Example University",
                "program_name": "Mechanical Engineering",
                "program_code": "BSME",
                "full_name": "Generic Owner",
                "email": "generic@example.edu",
                "password": "generic-password-long",
            },
        )
        self.assertEqual(response.status_code, 302)

        with generic_app.app_context():
            db = get_db()
            self.assertIsNone(
                db.execute(
                    "SELECT version FROM schema_versions WHERE version=5"
                ).fetchone()
            )
            program_id = db.execute("SELECT id FROM programs").fetchone()[0]
            user_id = db.execute("SELECT id FROM users").fetchone()[0]
            course_id = db.execute(
                """INSERT INTO courses(program_id,code,name)
                   VALUES (?,'ME 101','Introduction to Engineering')""",
                (program_id,),
            ).lastrowid
            outcome_id = db.execute(
                "SELECT id FROM outcomes WHERE program_id=? ORDER BY id LIMIT 1",
                (program_id,),
            ).fetchone()[0]
            record_id = db.execute(
                """INSERT INTO assessment_records
                   (program_id,term_id,course_id,outcome_id,indicator_id,rubric_id,
                    collected_by,campus,method,assessment_tool,bloom_level,
                    sample_size,target,status)
                   SELECT ?,t.id,?,o.id,pi.id,r.id,?,'Unassigned','direct',
                          'Pre-UTRGV current source row','Analyze',10000,70,'draft'
                     FROM academic_terms t,outcomes o
                     JOIN performance_indicators pi ON pi.outcome_id=o.id,
                          rubrics r
                    WHERE t.program_id=? AND o.id=? AND r.program_id=? LIMIT 1""",
                (
                    program_id,
                    course_id,
                    user_id,
                    program_id,
                    outcome_id,
                    program_id,
                ),
            ).lastrowid
            db.execute(
                """INSERT INTO legacy_import_items
                   (program_id,source_fingerprint,source_record_id,assessment_id,
                    expert_percent,practitioner_percent,apprentice_percent,novice_percent)
                   VALUES (?,?,1,?,40,30,20,10)""",
                (program_id, "generic-before-utrgv", record_id),
            )
            db.commit()

        utrgv_config = {
            **generic_config,
            "EDITION": "utrgv_mece",
            "PRODUCT_NAME": "UTRGV ME Accreditation Hub",
            "CUSTOMER_NAME": "UTRGV Department of Mechanical Engineering",
        }
        utrgv_app = create_app(utrgv_config)
        with utrgv_app.app_context():
            db = get_db()
            self.assertEqual(
                db.execute(
                    "SELECT campus FROM assessment_records WHERE id=?", (record_id,)
                ).fetchone()[0],
                "Edinburg",
            )
            self.assertEqual(
                db.execute(
                    """SELECT COUNT(*) FROM assessment_revisions
                       WHERE assessment_id=?""",
                    (record_id,),
                ).fetchone()[0],
                1,
            )
            self.assertIsNotNone(
                db.execute(
                    "SELECT version FROM schema_versions WHERE version=5"
                ).fetchone()
            )


if __name__ == "__main__":
    unittest.main()
