from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from abet_platform import create_app
from abet_platform.db import get_db
from abet_platform.legacy_import import import_legacy_records


LEGACY_SCHEMA = """
CREATE TABLE abet_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course TEXT, course_name TEXT, slo TEXT, pi TEXT, assessment_tool TEXT,
    explanation TEXT, semester TEXT, blooms_level TEXT, expert REAL,
    practitioner REAL, apprentice REAL, novice REAL, observations TEXT
);
"""


class LegacyCampusImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        edinburg_dir = root / "edinburg"
        brownsville_dir = root / "brownsville"
        edinburg_dir.mkdir()
        brownsville_dir.mkdir()
        # Matching basenames and overlapping row IDs are intentional. Source
        # identity must come from the configured source key and campus, not the
        # filename or source_record_id alone.
        self.edinburg_source = edinburg_dir / "abet_data.db"
        self.brownsville_source = brownsville_dir / "abet_data.db"
        self._create_source(
            self.edinburg_source,
            tool="Edinburg historical laboratory",
            expert=45.25,
            practitioner=35.0,
            apprentice=14.75,
            novice=5.0,
        )
        self._create_source(
            self.brownsville_source,
            tool="Brownsville historical examination",
            expert=40.0,
            practitioner=30.0,
            apprentice=20.0,
            novice=10.0,
        )
        self.source_bytes = {
            "Edinburg": self.edinburg_source.read_bytes(),
            "Brownsville": self.brownsville_source.read_bytes(),
        }
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "legacy-campus-test-secret",
                "DATABASE": str(root / "utrgv.db"),
                "UPLOAD_FOLDER": str(root / "uploads"),
                "EDITION": "utrgv_mece",
                "PRODUCT_NAME": "UTRGV ME Accreditation Hub",
                "CUSTOMER_NAME": "UTRGV Department of Mechanical Engineering",
                "LEGACY_SOURCES": {
                    "Edinburg": str(self.edinburg_source),
                    "Brownsville": str(self.brownsville_source),
                },
            }
        )
        self.client = self.app.test_client()
        self._setup_owner()
        with self.app.app_context():
            db = get_db()
            self.program_id = db.execute(
                "SELECT id FROM programs WHERE code='BSME'"
            ).fetchone()[0]
            self.owner_id = db.execute(
                "SELECT id FROM users WHERE email='isaac.palli@utrgv.edu'"
            ).fetchone()[0]

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def _create_source(path: Path, *, tool: str, expert, practitioner, apprentice, novice):
        with sqlite3.connect(path) as connection:
            connection.executescript(LEGACY_SCHEMA)
            connection.execute(
                """INSERT INTO abet_entries
                   (id,course,course_name,slo,pi,assessment_tool,explanation,semester,
                    blooms_level,expert,practitioner,apprentice,novice,observations)
                   VALUES (1,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    "MECE 3320",
                    "Measurements & Instrumentation",
                    "SLO1",
                    "PI-3: Able to solve Problem",
                    tool,
                    "Aligned historical evidence",
                    "Fall 2024",
                    "Analyze",
                    expert,
                    practitioner,
                    apprentice,
                    novice,
                    f"Preserved observation for {tool}",
                ),
            )

    def csrf(self):
        with self.client.session_transaction() as session:
            return session["csrf_token"]

    def _setup_owner(self):
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
        self.client.get("/login")
        response = self.client.post(
            "/login",
            data={
                "csrf_token": self.csrf(),
                "login": "isaac.palli@utrgv.edu",
                "password": "owner-password-long",
            },
        )
        self.assertEqual(response.status_code, 302)

    def test_same_filename_and_overlapping_record_ids_import_per_campus_independently(self):
        for source_key in ("edinburg", "brownsville"):
            response = self.client.post(
                "/utrgv/legacy/import",
                data={"csrf_token": self.csrf(), "source_key": source_key},
            )
            self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            imported = db.execute(
                """SELECT ar.campus,ar.assessment_tool,li.source_record_id,
                          li.source_fingerprint,li.expert_percent,li.practitioner_percent
                   FROM legacy_import_items li
                   JOIN assessment_records ar ON ar.id=li.assessment_id
                   ORDER BY ar.campus"""
            ).fetchall()
            self.assertEqual(len(imported), 2)
            self.assertEqual({row["source_record_id"] for row in imported}, {1})
            self.assertEqual({row["campus"] for row in imported}, {"Edinburg", "Brownsville"})
            self.assertEqual(len({row["source_fingerprint"] for row in imported}), 2)
            by_campus = {row["campus"]: row for row in imported}
            self.assertEqual(
                by_campus["Edinburg"]["assessment_tool"],
                "Edinburg historical laboratory",
            )
            self.assertEqual(by_campus["Edinburg"]["expert_percent"], 45.25)
            self.assertEqual(
                by_campus["Brownsville"]["assessment_tool"],
                "Brownsville historical examination",
            )
            self.assertEqual(by_campus["Brownsville"]["practitioner_percent"], 30.0)

            audit_details = [
                json.loads(row["details_json"])
                for row in db.execute(
                    """SELECT details_json FROM audit_events
                       WHERE action='import' AND entity_type='utrgv_legacy_archive'
                       ORDER BY id"""
                )
            ]
            self.assertEqual(
                {(item["source_key"], item["campus"]) for item in audit_details},
                {("edinburg", "Edinburg"), ("brownsville", "Brownsville")},
            )
            self.assertTrue(all(item["imported"] == 1 for item in audit_details))

        # Re-importing each source is independently idempotent.
        for source_key in ("edinburg", "brownsville"):
            self.client.post(
                "/utrgv/legacy/import",
                data={"csrf_token": self.csrf(), "source_key": source_key},
            )
        with self.app.app_context():
            db = get_db()
            self.assertEqual(db.execute("SELECT COUNT(*) FROM assessment_records").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM legacy_import_items").fetchone()[0], 2)

        self.assertEqual(self.edinburg_source.read_bytes(), self.source_bytes["Edinburg"])
        self.assertEqual(self.brownsville_source.read_bytes(), self.source_bytes["Brownsville"])

    def test_unassigned_historical_rows_require_audited_batch_mapping_before_submit(self):
        # This models an import made before campus provenance was available.
        # The importer must preserve that uncertainty rather than guessing.
        with self.app.app_context():
            db = get_db()
            with db:
                result = import_legacy_records(
                    db,
                    self.edinburg_source,
                    program_id=self.program_id,
                    imported_by=self.owner_id,
                    source_key="historical-no-campus",
                )
            self.assertEqual(result["campus"], "Unassigned")
            record = db.execute(
                """SELECT ar.id,ar.campus,ar.status,li.expert_percent,li.practitioner_percent
                   FROM assessment_records ar
                   JOIN legacy_import_items li ON li.assessment_id=ar.id"""
            ).fetchone()
            self.assertEqual(record["campus"], "Unassigned")
            self.assertEqual(record["status"], "draft")
            self.assertEqual(record["expert_percent"], 45.25)
            self.assertEqual(record["practitioner_percent"], 35.0)
            record_id = record["id"]

        blocked = self.client.post(
            f"/assessments/{record_id}/status",
            data={"csrf_token": self.csrf(), "action": "submit"},
        )
        self.assertEqual(blocked.status_code, 400)
        self.assertIn(b"Edinburg or Brownsville", blocked.data)
        with self.app.app_context():
            unresolved = get_db().execute(
                "SELECT campus,status FROM assessment_records WHERE id=?", (record_id,)
            ).fetchone()
            self.assertEqual(tuple(unresolved), ("Unassigned", "draft"))

        assigned = self.client.post(
            "/utrgv/legacy/assign-campus",
            data={"csrf_token": self.csrf(), "campus": "Brownsville"},
        )
        self.assertEqual(assigned.status_code, 302)
        with self.app.app_context():
            db = get_db()
            mapped = db.execute(
                """SELECT ar.campus,ar.status,li.expert_percent,li.practitioner_percent
                   FROM assessment_records ar
                   JOIN legacy_import_items li ON li.assessment_id=ar.id
                   WHERE ar.id=?""",
                (record_id,),
            ).fetchone()
            self.assertEqual(mapped["campus"], "Brownsville")
            self.assertEqual(mapped["status"], "draft")
            self.assertEqual(mapped["expert_percent"], 45.25)
            self.assertEqual(mapped["practitioner_percent"], 35.0)
            audit_row = db.execute(
                """SELECT entity_type,details_json FROM audit_events
                   WHERE action='assign_campus' ORDER BY id DESC LIMIT 1"""
            ).fetchone()
            self.assertEqual(audit_row["entity_type"], "utrgv_legacy_archive")
            self.assertEqual(
                json.loads(audit_row["details_json"]),
                {
                    "campus": "Brownsville",
                    "records": 1,
                    "administrative_change": True,
                    "review_reset": 0,
                },
            )

        submitted = self.client.post(
            f"/assessments/{record_id}/status",
            data={"csrf_token": self.csrf(), "action": "submit"},
        )
        self.assertEqual(submitted.status_code, 302)
        with self.app.app_context():
            submitted_record = get_db().execute(
                "SELECT campus,status FROM assessment_records WHERE id=?", (record_id,)
            ).fetchone()
            self.assertEqual(tuple(submitted_record), ("Brownsville", "submitted"))

    def test_administrator_correction_changes_portal_copy_not_source_database(self):
        imported = self.client.post(
            "/utrgv/legacy/import",
            data={"csrf_token": self.csrf(), "source_key": "edinburg"},
        )
        self.assertEqual(imported.status_code, 302)
        with self.app.app_context():
            db = get_db()
            record = db.execute(
                """SELECT ar.* FROM assessment_records ar
                   JOIN legacy_import_items li ON li.assessment_id=ar.id
                   WHERE ar.campus='Edinburg'"""
            ).fetchone()
            record_id = record["id"]

        response = self.client.post(
            f"/assessments/{record_id}/edit",
            data={
                "csrf_token": self.csrf(),
                "record_version": str(record["record_version"]),
                "campus": "Brownsville",
                "term_id": str(record["term_id"]),
                "course_id": str(record["course_id"]),
                "outcome_id": str(record["outcome_id"]),
                "indicator_id": str(record["indicator_id"]),
                "rubric_id": str(record["rubric_id"]),
                "method": record["method"],
                "assessment_tool": "Administrator-corrected portal copy",
                "bloom_level": record["bloom_level"],
                "target": str(record["target"]),
                "rationale": record["rationale"],
                "observations": record["observations"],
                "action_notes": record["action_notes"],
                "expert_percent": "50",
                "practitioner_percent": "30",
                "apprentice_percent": "15",
                "novice_percent": "5",
                "admin_change_note": "Corrected the portal copy after source verification.",
            },
        )
        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            changed = get_db().execute(
                """SELECT ar.campus,ar.assessment_tool,li.expert_percent
                   FROM assessment_records ar
                   JOIN legacy_import_items li ON li.assessment_id=ar.id
                   WHERE ar.id=?""",
                (record_id,),
            ).fetchone()
            self.assertEqual(
                tuple(changed),
                ("Brownsville", "Administrator-corrected portal copy", 50.0),
            )
        self.assertEqual(self.edinburg_source.read_bytes(), self.source_bytes["Edinburg"])

    def test_bulk_campus_mapping_reopens_workflow_and_revises_every_record(self):
        with self.app.app_context():
            db = get_db()
            with db:
                first = import_legacy_records(
                    db,
                    self.edinburg_source,
                    program_id=self.program_id,
                    imported_by=self.owner_id,
                    source_key="unresolved-first",
                )
                second = import_legacy_records(
                    db,
                    self.brownsville_source,
                    program_id=self.program_id,
                    imported_by=self.owner_id,
                    source_key="unresolved-second",
                )
                record_ids = [
                    db.execute(
                        """SELECT assessment_id FROM legacy_import_items
                           WHERE program_id=? AND source_fingerprint=?""",
                        (self.program_id, result["fingerprint"]),
                    ).fetchone()[0]
                    for result in (first, second)
                ]
                db.execute(
                    """UPDATE assessment_records
                       SET status='submitted',submitted_at='2026-08-10 10:00:00'
                       WHERE id=?""",
                    (record_ids[0],),
                )
                db.execute(
                    """UPDATE assessment_records
                       SET status='approved',submitted_at='2026-08-10 10:00:00',
                           approved_at='2026-08-11 11:00:00',approved_by=?
                       WHERE id=?""",
                    (self.owner_id, record_ids[1]),
                )

        response = self.client.post(
            "/utrgv/legacy/assign-campus",
            data={"csrf_token": self.csrf(), "campus": "Brownsville"},
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            db = get_db()
            records = db.execute(
                """SELECT id,campus,status,submitted_at,approved_at,approved_by
                   FROM assessment_records WHERE id IN (?,?) ORDER BY id""",
                tuple(record_ids),
            ).fetchall()
            self.assertEqual(len(records), 2)
            for record in records:
                self.assertEqual(record["campus"], "Brownsville")
                self.assertEqual(record["status"], "draft")
                self.assertIsNone(record["submitted_at"])
                self.assertIsNone(record["approved_at"])
                self.assertIsNone(record["approved_by"])

            revisions = db.execute(
                """SELECT assessment_id,changed_by,changed_by_name,change_note,
                          before_json,after_json
                   FROM assessment_revisions
                   WHERE assessment_id IN (?,?) ORDER BY assessment_id""",
                tuple(record_ids),
            ).fetchall()
            self.assertEqual(len(revisions), 2)
            self.assertEqual(
                {row["assessment_id"] for row in revisions}, set(record_ids)
            )
            for revision in revisions:
                self.assertEqual(revision["changed_by"], self.owner_id)
                self.assertEqual(revision["changed_by_name"], "Accreditation Director")
                self.assertTrue(revision["change_note"].strip())
                before = json.loads(revision["before_json"])
                after = json.loads(revision["after_json"])
                self.assertEqual(before["campus"], "Unassigned")
                self.assertIn(before["status"], {"submitted", "approved"})
                self.assertEqual(after["campus"], "Brownsville")
                self.assertEqual(after["status"], "draft")

            event = db.execute(
                """SELECT details_json FROM audit_events
                   WHERE action='assign_campus' ORDER BY id DESC LIMIT 1"""
            ).fetchone()
            details = json.loads(event["details_json"])
            self.assertEqual(details["records"], 2)
            self.assertEqual(details["campus"], "Brownsville")
            self.assertTrue(details["administrative_change"])
            self.assertTrue(details["review_reset"])


if __name__ == "__main__":
    unittest.main()
