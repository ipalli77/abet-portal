from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from abet_platform.legacy_reader import (
    LegacySchemaError,
    LegacySourceError,
    filter_options,
    list_records,
    source_metadata,
    summarize_records,
    validate_source,
)


SCHEMA = """
CREATE TABLE abet_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course TEXT,
    course_name TEXT,
    slo TEXT,
    pi TEXT,
    assessment_tool TEXT,
    explanation TEXT,
    semester TEXT,
    blooms_level TEXT,
    expert REAL,
    practitioner REAL,
    apprentice REAL,
    novice REAL,
    observations TEXT
);
"""


class LegacyReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "legacy #1?.db"
        with sqlite3.connect(self.database) as connection:
            connection.executescript(SCHEMA)
            connection.executemany(
                """INSERT INTO abet_entries
                   (course, course_name, slo, pi, assessment_tool, explanation, semester,
                    blooms_level, expert, practitioner, apprentice, novice, observations)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        "MECE 2301",
                        "Statics",
                        "SLO1",
                        "PI 1.1",
                        "Final exam",
                        "Direct assessment",
                        "Fall 2025",
                        "Apply",
                        45,
                        35,
                        15,
                        5,
                        "Target met",
                    ),
                    (
                        "MECE 2301",
                        "Statics",
                        "SLO2",
                        "PI 2.1",
                        "Design project",
                        "Direct assessment",
                        "Spring 2026",
                        "Analyze",
                        30,
                        30,
                        25,
                        15,
                        "Add a review module",
                    ),
                    (
                        "MECE 3380",
                        "Kinematics & Dynamics of Machines",
                        "SLO1",
                        "PI 1.2",
                        "Project rubric",
                        "Direct assessment",
                        "Spring 2026",
                        "Create",
                        55,
                        35,
                        8,
                        2,
                        "Target met",
                    ),
                ],
            )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_validates_schema_and_special_character_path_in_read_only_mode(self) -> None:
        before = self.database.read_bytes()

        self.assertEqual(validate_source(self.database), self.database.resolve())
        self.assertEqual(list_records(self.database)["total"], 3)

        # A read must not create a journal or change the source file.
        self.assertEqual(self.database.read_bytes(), before)
        self.assertFalse(Path(f"{self.database}-journal").exists())

    def test_rejects_missing_invalid_and_incomplete_sources(self) -> None:
        with self.assertRaises(LegacySourceError):
            validate_source(Path(self.temp.name) / "missing.db")
        with self.assertRaises(LegacySourceError):
            validate_source(Path(self.temp.name))

        invalid = Path(self.temp.name) / "invalid.db"
        invalid.write_text("not sqlite", encoding="utf-8")
        with self.assertRaises(LegacySourceError):
            validate_source(invalid)

        incomplete = Path(self.temp.name) / "incomplete.db"
        with sqlite3.connect(incomplete) as connection:
            connection.execute("CREATE TABLE abet_entries (id INTEGER PRIMARY KEY, course TEXT)")
        with self.assertRaisesRegex(LegacySchemaError, "missing required columns"):
            validate_source(incomplete)

    def test_summary_and_filter_options(self) -> None:
        self.assertEqual(
            summarize_records(self.database),
            {
                "record_count": 3,
                "course_count": 2,
                "semester_count": 2,
                "outcome_count": 2,
                "records_with_observations": 3,
                "average_attainment": 76.7,
            },
        )
        self.assertEqual(summarize_records(self.database, semester="Spring 2026")["record_count"], 2)
        self.assertEqual(summarize_records(self.database, search="review module")["record_count"], 1)
        self.assertEqual(
            filter_options(self.database),
            {
                "course": ["MECE 2301", "MECE 3380"],
                "semester": ["Fall 2025", "Spring 2026"],
                "slo": ["SLO1", "SLO2"],
            },
        )

    def test_filtered_paginated_records_are_parameterized_and_bounded(self) -> None:
        first_page = list_records(self.database, slo="SLO1", page=1, per_page=1)
        self.assertEqual(first_page["total"], 2)
        self.assertEqual(first_page["pages"], 2)
        self.assertFalse(first_page["has_previous"])
        self.assertTrue(first_page["has_next"])
        self.assertEqual(first_page["records"][0]["course"], "MECE 3380")

        second_page = list_records(self.database, slo="SLO1", page=2, per_page=1)
        self.assertTrue(second_page["has_previous"])
        self.assertFalse(second_page["has_next"])
        self.assertEqual(second_page["records"][0]["course"], "MECE 2301")

        # Quotes are data, not SQL, and LIKE wildcards are treated literally.
        self.assertEqual(list_records(self.database, course="' OR 1=1 --")["total"], 0)
        self.assertEqual(list_records(self.database, search="%")["total"], 0)
        with self.assertRaises(ValueError):
            list_records(self.database, page=0)
        with self.assertRaises(ValueError):
            list_records(self.database, per_page=201)

    def test_metadata_is_safe_and_fingerprints_file_content(self) -> None:
        metadata = source_metadata(self.database)

        self.assertEqual(metadata["filename"], self.database.name)
        self.assertEqual(metadata["size_bytes"], self.database.stat().st_size)
        self.assertEqual(metadata["sha256"], hashlib.sha256(self.database.read_bytes()).hexdigest())
        self.assertIn("+00:00", metadata["modified_at"])
        self.assertNotIn("path", metadata)
        self.assertNotIn(str(self.database.parent), repr(metadata))


if __name__ == "__main__":
    unittest.main()
