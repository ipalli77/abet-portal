from __future__ import annotations

import csv
import io
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from abet_platform import create_app
from abet_platform.db import get_db


class _NamedFieldParser(HTMLParser):
    """Collect named form controls without adding a test-only HTML dependency."""

    def __init__(self) -> None:
        super().__init__()
        self.fields: dict[str, list[dict[str, str | None]]] = {}

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag not in {"input", "select", "textarea"}:
            return
        attributes = dict(attrs)
        name = attributes.get("name")
        if name:
            self.fields.setdefault(name, []).append(attributes)


def _named_fields(html: bytes) -> dict[str, list[dict[str, str | None]]]:
    parser = _NamedFieldParser()
    parser.feed(html.decode("utf-8"))
    return parser.fields


class UtrgvPercentageAssessmentTests(unittest.TestCase):
    """Customer contract for percentage-basis EPAN assessment entry."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "utrgv-percentage-test-secret",
                "DATABASE": str(root / "utrgv.db"),
                "UPLOAD_FOLDER": str(root / "uploads"),
                "EDITION": "utrgv_mece",
                "PRODUCT_NAME": "UTRGV ME Accreditation Hub",
                "CUSTOMER_NAME": "UTRGV Department of Mechanical Engineering",
            }
        )
        self.client = self.app.test_client()
        self._setup_and_login()
        with self.app.app_context():
            db = get_db()
            outcome = db.execute(
                "SELECT id FROM outcomes WHERE code='SLO1'"
            ).fetchone()
            self.dimensions = {
                "term_id": db.execute(
                    "SELECT id FROM academic_terms ORDER BY sort_order DESC,id DESC LIMIT 1"
                ).fetchone()[0],
                "course_id": db.execute(
                    "SELECT id FROM courses WHERE code='MECE 3320'"
                ).fetchone()[0],
                "outcome_id": outcome["id"],
                "indicator_id": db.execute(
                    """SELECT id FROM performance_indicators
                       WHERE outcome_id=? ORDER BY display_order,id LIMIT 1""",
                    (outcome["id"],),
                ).fetchone()[0],
                "rubric_id": db.execute(
                    """SELECT id FROM rubrics WHERE name='EPAN' COLLATE NOCASE
                       ORDER BY is_default DESC,id LIMIT 1"""
                ).fetchone()[0],
            }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def csrf(self) -> str:
        with self.client.session_transaction() as session:
            return session["csrf_token"]

    def _setup_and_login(self) -> None:
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

    def payload(
        self,
        *,
        percentages: tuple[str, str, str, str] = (
            "33.333333",
            "33.333333",
            "16.666667",
            "16.666667",
        ),
        tool: str = "Fractional EPAN laboratory assessment",
    ) -> dict[str, str | int]:
        return {
            "csrf_token": self.csrf(),
            "campus": "Edinburg",
            "term_id": self.dimensions["term_id"],
            "course_id": self.dimensions["course_id"],
            "outcome_id": self.dimensions["outcome_id"],
            "indicator_id": self.dimensions["indicator_id"],
            # The rubric is fixed by the UTRGV edition. Including this value
            # also verifies that a legacy client payload remains harmless.
            "rubric_id": self.dimensions["rubric_id"],
            "method": "direct",
            "assessment_tool": tool,
            "bloom_level": "Analyze",
            "target": "70.5",
            "expert_percent": percentages[0],
            "practitioner_percent": percentages[1],
            "apprentice_percent": percentages[2],
            "novice_percent": percentages[3],
            "rationale": "The laboratory task directly measures the selected PI.",
            "observations": "Students were strongest in model selection.",
            "action_notes": "Add a calibration exercise before the next offering.",
        }

    def _record_count(self) -> int:
        with self.app.app_context():
            return get_db().execute(
                "SELECT COUNT(*) FROM assessment_records"
            ).fetchone()[0]

    def _latest_record_id(self) -> int:
        with self.app.app_context():
            return get_db().execute(
                "SELECT id FROM assessment_records ORDER BY id DESC LIMIT 1"
            ).fetchone()[0]

    def test_form_uses_required_epan_percentages_and_has_no_sample_size(self) -> None:
        response = self.client.get("/assessments/new")
        self.assertEqual(response.status_code, 200)
        fields = _named_fields(response.data)

        self.assertNotIn("sample_size", fields)
        self.assertNotIn(b'id="sample-size"', response.data)
        self.assertNotIn(b"Counts must equal sample size", response.data)
        self.assertIn(b"EPAN total must equal 100%", response.data)

        required_fields = {
            "campus",
            "term_id",
            "course_id",
            "outcome_id",
            "indicator_id",
            "method",
            "assessment_tool",
            "bloom_level",
            "target",
            "expert_percent",
            "practitioner_percent",
            "apprentice_percent",
            "novice_percent",
            "rationale",
            "observations",
            "action_notes",
        }
        for name in required_fields:
            with self.subTest(field=name):
                self.assertIn(name, fields)
                self.assertIn("required", fields[name][0])

        for name in (
            "expert_percent",
            "practitioner_percent",
            "apprentice_percent",
            "novice_percent",
        ):
            attributes = fields[name][0]
            self.assertEqual(attributes.get("type"), "number")
            self.assertEqual(attributes.get("min"), "0")
            self.assertEqual(attributes.get("max"), "100")
            self.assertIn(attributes.get("step"), {"any", "0.01", "0.001"})

        # Bloom is a required assessment dimension for this customer, so the
        # percentage-entry form must not offer an empty "not applicable" choice.
        self.assertNotIn(b"Not applicable", response.data)

    def test_server_rejects_every_missing_required_assessment_field(self) -> None:
        required_fields = (
            "campus",
            "term_id",
            "course_id",
            "outcome_id",
            "indicator_id",
            "method",
            "assessment_tool",
            "bloom_level",
            "target",
            "expert_percent",
            "practitioner_percent",
            "apprentice_percent",
            "novice_percent",
            "rationale",
            "observations",
            "action_notes",
        )
        for name in required_fields:
            with self.subTest(field=name):
                payload = self.payload()
                payload[name] = ""
                response = self.client.post(
                    "/assessments/new", data=payload, follow_redirects=True
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn(b'class="flash error"', response.data)
                self.assertEqual(self._record_count(), 0)

    def test_fractional_percentages_are_stored_without_a_synthetic_sample(self) -> None:
        # These decimal inputs total mathematically to 100 but their binary
        # floating-point sum is 100.00000000000001. The validation must use a
        # tiny numerical tolerance without accepting a visible .01-point error.
        percentages = ("33.333333", "33.333333", "16.666667", "16.666667")
        payload = self.payload(percentages=percentages)
        self.assertNotIn("sample_size", payload)
        response = self.client.post("/assessments/new", data=payload)
        self.assertEqual(response.status_code, 302)

        record_id = self._latest_record_id()
        with self.app.app_context():
            db = get_db()
            record = db.execute(
                "SELECT result_basis,sample_size FROM assessment_records WHERE id=?",
                (record_id,),
            ).fetchone()
            self.assertEqual(record["result_basis"], "percentages")
            self.assertIsNone(record["sample_size"])
            results = db.execute(
                """SELECT rl.label,rs.level_percent
                   FROM assessment_results rs
                   JOIN rubric_levels rl ON rl.id=rs.rubric_level_id
                   WHERE rs.assessment_id=? ORDER BY rl.display_order,rl.id""",
                (record_id,),
            ).fetchall()
            self.assertEqual(len(results), 4)
            for result, expected in zip(results, map(float, percentages), strict=True):
                self.assertAlmostEqual(result["level_percent"], expected, places=6)

        edit_page = self.client.get(f"/assessments/{record_id}/edit")
        fields = _named_fields(edit_page.data)
        for name, expected in zip(
            (
                "expert_percent",
                "practitioner_percent",
                "apprentice_percent",
                "novice_percent",
            ),
            percentages,
            strict=True,
        ):
            self.assertAlmostEqual(
                float(fields[name][0]["value"]), float(expected), places=6
            )

    def test_invalid_epan_values_and_non_100_totals_alert_without_saving(self) -> None:
        invalid_distributions = {
            "under by one hundredth": ("25", "25", "25", "24.99"),
            "over by one hundredth": ("25", "25", "25", "25.01"),
            "negative": ("-0.01", "40", "30", "30.01"),
            "over 100 category": ("100.01", "0", "0", "-0.01"),
            "nan": ("nan", "30", "30", "40"),
            "positive infinity": ("inf", "0", "0", "0"),
            "negative infinity": ("-inf", "30", "30", "40"),
        }
        for label, percentages in invalid_distributions.items():
            with self.subTest(case=label):
                response = self.client.post(
                    "/assessments/new",
                    data=self.payload(percentages=percentages),
                    follow_redirects=True,
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn(b'class="flash error"', response.data)
                self.assertEqual(self._record_count(), 0)

    def test_incomplete_or_tampered_records_cannot_enter_official_review(self) -> None:
        # Old or directly migrated rows can predate the mandatory-field rules.
        # Workflow transitions must revalidate persisted evidence rather than
        # relying solely on validation performed by the current edit form.
        self.client.post(
            "/assessments/new",
            data=self.payload(tool="Incomplete preexisting assessment"),
        )
        missing_narrative_id = self._latest_record_id()
        with self.app.app_context():
            db = get_db()
            db.execute(
                "UPDATE assessment_records SET action_notes='' WHERE id=?",
                (missing_narrative_id,),
            )
            db.commit()
        response = self.client.post(
            f"/assessments/{missing_narrative_id}/status",
            data={"csrf_token": self.csrf(), "action": "submit"},
        )
        self.assertEqual(response.status_code, 400)

        self.client.post(
            "/assessments/new",
            data=self.payload(tool="Count-basis preexisting assessment"),
        )
        count_basis_id = self._latest_record_id()
        with self.app.app_context():
            db = get_db()
            db.execute(
                """UPDATE assessment_records
                   SET result_basis='student_counts',sample_size=100
                   WHERE id=?""",
                (count_basis_id,),
            )
            db.execute(
                "UPDATE assessment_results SET level_percent=NULL WHERE assessment_id=?",
                (count_basis_id,),
            )
            db.commit()
        response = self.client.post(
            f"/assessments/{count_basis_id}/status",
            data={"csrf_token": self.csrf(), "action": "submit"},
        )
        self.assertEqual(response.status_code, 400)

        self.client.post(
            "/assessments/new",
            data=self.payload(tool="Assessment tampered after submission"),
        )
        tampered_id = self._latest_record_id()
        submitted = self.client.post(
            f"/assessments/{tampered_id}/status",
            data={"csrf_token": self.csrf(), "action": "submit"},
        )
        self.assertEqual(submitted.status_code, 302)
        with self.app.app_context():
            db = get_db()
            novice_level = db.execute(
                """SELECT rl.id FROM rubric_levels rl
                   JOIN assessment_records ar ON ar.rubric_id=rl.rubric_id
                   WHERE ar.id=? AND rl.label='Novice' COLLATE NOCASE""",
                (tampered_id,),
            ).fetchone()[0]
            db.execute(
                """UPDATE assessment_results SET level_percent=level_percent-0.01
                   WHERE assessment_id=? AND rubric_level_id=?""",
                (tampered_id, novice_level),
            )
            db.commit()
        rejected = self.client.post(
            f"/assessments/{tampered_id}/status",
            data={"csrf_token": self.csrf(), "action": "approve"},
        )
        self.assertEqual(rejected.status_code, 400)

        with self.app.app_context():
            statuses = {
                row["id"]: row["status"]
                for row in get_db().execute(
                    """SELECT id,status FROM assessment_records
                       WHERE id IN (?,?,?)""",
                    (missing_narrative_id, count_basis_id, tampered_id),
                )
            }
        self.assertEqual(statuses[missing_narrative_id], "draft")
        self.assertEqual(statuses[count_basis_id], "draft")
        self.assertEqual(statuses[tampered_id], "submitted")

    def test_edit_roundtrip_drives_analytics_and_percentage_csv_export(self) -> None:
        response = self.client.post("/assessments/new", data=self.payload())
        self.assertEqual(response.status_code, 302)
        record_id = self._latest_record_id()
        with self.app.app_context():
            version = get_db().execute(
                "SELECT record_version FROM assessment_records WHERE id=?",
                (record_id,),
            ).fetchone()[0]

        edit_page = self.client.get(f"/assessments/{record_id}/edit")
        fields = _named_fields(edit_page.data)
        self.assertIn("admin_change_note", fields)
        self.assertIn("required", fields["admin_change_note"][0])

        edited_percentages = ("12.5", "62.25", "20", "5.25")
        missing_note = self.payload(
            percentages=edited_percentages, tool="Edited percentage assessment"
        )
        missing_note["record_version"] = str(version)
        response = self.client.post(
            f"/assessments/{record_id}/edit",
            data=missing_note,
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'class="flash error"', response.data)
        with self.app.app_context():
            unchanged = get_db().execute(
                "SELECT assessment_tool,record_version FROM assessment_records WHERE id=?",
                (record_id,),
            ).fetchone()
            self.assertEqual(unchanged["assessment_tool"], "Fractional EPAN laboratory assessment")
            self.assertEqual(unchanged["record_version"], version)

        edited = dict(missing_note)
        edited["admin_change_note"] = (
            "Corrected the percentages from the signed faculty worksheet."
        )
        response = self.client.post(
            f"/assessments/{record_id}/edit", data=edited
        )
        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            persisted = db.execute(
                """SELECT rl.label,rs.level_percent
                   FROM assessment_results rs
                   JOIN rubric_levels rl ON rl.id=rs.rubric_level_id
                   WHERE rs.assessment_id=? ORDER BY rl.display_order,rl.id""",
                (record_id,),
            ).fetchall()
            self.assertEqual(
                [row["level_percent"] for row in persisted],
                list(map(float, edited_percentages)),
            )

        self.client.post(
            f"/assessments/{record_id}/status",
            data={"csrf_token": self.csrf(), "action": "submit"},
        )
        self.client.post(
            f"/assessments/{record_id}/status",
            data={"csrf_token": self.csrf(), "action": "approve"},
        )

        analytics = self.client.get("/analytics?view=records")
        self.assertEqual(analytics.status_code, 200)
        self.assertIn(b"74.75%", analytics.data)

        exported = self.client.get("/export/assessments.csv")
        self.assertEqual(exported.status_code, 200)
        rows = list(csv.DictReader(io.StringIO(exported.text)))
        self.assertEqual(len(rows), 1)
        self.assertNotIn("sample_size", rows[0])
        self.assertEqual(rows[0]["result_basis"], "percentages")
        for name, expected in zip(
            (
                "expert_percent",
                "practitioner_percent",
                "apprentice_percent",
                "novice_percent",
            ),
            edited_percentages,
            strict=True,
        ):
            self.assertAlmostEqual(float(rows[0][name]), float(expected), places=6)
        self.assertAlmostEqual(float(rows[0]["attainment"]), 74.75, places=6)

    def test_utrgv_csv_template_and_import_use_percentage_fields(self) -> None:
        template = self.client.get("/import/template.csv")
        self.assertEqual(template.status_code, 200)
        header = next(csv.reader(io.StringIO(template.text)))
        self.assertNotIn("sample_size", header)
        for name in (
            "expert_percent",
            "practitioner_percent",
            "apprentice_percent",
            "novice_percent",
        ):
            self.assertIn(name, header)

        csv_row = {
            "campus": "Brownsville",
            "term": self._dimension_label("academic_terms", self.dimensions["term_id"], "name"),
            "course": self._dimension_label("courses", self.dimensions["course_id"], "code"),
            "outcome": self._dimension_label("outcomes", self.dimensions["outcome_id"], "code"),
            "indicator": self._dimension_label(
                "performance_indicators", self.dimensions["indicator_id"], "code"
            ),
            "rubric": "EPAN",
            "method": "direct",
            "assessment_tool": "Imported percentage assessment",
            "bloom_level": "Apply",
            "target": "70",
            "expert_percent": "45.25",
            "practitioner_percent": "35.5",
            "apprentice_percent": "14.25",
            "novice_percent": "5",
            "rationale": "Imported aligned measure rationale.",
            "observations": "Imported interpretation.",
            "action_notes": "Imported improvement action.",
        }
        imported = self._upload_csv(header, csv_row)
        self.assertEqual(imported.status_code, 200)
        self.assertIn(b"Imported 1 draft assessment record", imported.data)
        with self.app.app_context():
            db = get_db()
            record = db.execute(
                """SELECT result_basis,sample_size,campus FROM assessment_records
                   WHERE assessment_tool='Imported percentage assessment'"""
            ).fetchone()
            self.assertIsNotNone(record)
            self.assertEqual(record["result_basis"], "percentages")
            self.assertIsNone(record["sample_size"])
            self.assertEqual(record["campus"], "Brownsville")

        for total_label, novice in (("99.99", "4.99"), ("100.01", "5.01")):
            with self.subTest(total=total_label):
                invalid_row = dict(csv_row)
                invalid_row["assessment_tool"] = f"Invalid total {total_label}"
                invalid_row["novice_percent"] = novice
                response = self._upload_csv(header, invalid_row)
                self.assertEqual(response.status_code, 200)
                self.assertIn(b'class="flash error"', response.data)
        with self.app.app_context():
            self.assertEqual(
                get_db().execute("SELECT COUNT(*) FROM assessment_records").fetchone()[0],
                1,
            )

    def _dimension_label(self, table: str, item_id: int, column: str) -> str:
        allowed = {
            "academic_terms": {"name"},
            "courses": {"code"},
            "outcomes": {"code"},
            "performance_indicators": {"code"},
        }
        if column not in allowed.get(table, set()):
            raise AssertionError("Unsafe test dimension query")
        with self.app.app_context():
            return get_db().execute(
                f"SELECT {column} FROM {table} WHERE id=?", (item_id,)
            ).fetchone()[0]

    def _upload_csv(self, header: list[str], row: dict[str, str]):
        content = io.StringIO()
        writer = csv.DictWriter(content, fieldnames=header)
        writer.writeheader()
        writer.writerow(row)
        return self.client.post(
            "/import/assessments.csv",
            data={
                "csrf_token": self.csrf(),
                "file": (io.BytesIO(content.getvalue().encode("utf-8")), "assessments.csv"),
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )


class GenericCountAssessmentCompatibilityTests(unittest.TestCase):
    """The commercial generic edition keeps its configurable count workflow."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "generic-count-test-secret",
                "DATABASE": str(root / "generic.db"),
                "UPLOAD_FOLDER": str(root / "uploads"),
            }
        )
        self.client = self.app.test_client()
        self.client.get("/setup")
        self.client.post(
            "/setup",
            data={
                "csrf_token": self.csrf(),
                "institution": "Example University",
                "program_name": "Mechanical Engineering",
                "program_code": "BSME",
                "full_name": "Program Owner",
                "email": "owner@example.edu",
                "password": "long-secure-password",
            },
        )
        self.client.get("/login")
        self.client.post(
            "/login",
            data={
                "csrf_token": self.csrf(),
                "email": "owner@example.edu",
                "password": "long-secure-password",
            },
        )
        self.client.post(
            "/configuration",
            data={
                "csrf_token": self.csrf(),
                "kind": "course",
                "code": "ME 301",
                "name": "Engineering Analysis",
                "description": "Core analysis course",
            },
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def csrf(self) -> str:
        with self.client.session_transaction() as session:
            return session["csrf_token"]

    def _payload(self, counts: tuple[int, int, int, int]) -> dict[str, str | int]:
        with self.app.app_context():
            db = get_db()
            outcome = db.execute(
                "SELECT id FROM outcomes ORDER BY display_order,id LIMIT 1"
            ).fetchone()
            rubric = db.execute(
                "SELECT id FROM rubrics ORDER BY is_default DESC,id LIMIT 1"
            ).fetchone()
            levels = db.execute(
                "SELECT id FROM rubric_levels WHERE rubric_id=? ORDER BY display_order,id",
                (rubric["id"],),
            ).fetchall()
            payload: dict[str, str | int] = {
                "csrf_token": self.csrf(),
                "term_id": db.execute("SELECT id FROM academic_terms LIMIT 1").fetchone()[0],
                "course_id": db.execute("SELECT id FROM courses LIMIT 1").fetchone()[0],
                "outcome_id": outcome["id"],
                "indicator_id": db.execute(
                    "SELECT id FROM performance_indicators WHERE outcome_id=? LIMIT 1",
                    (outcome["id"],),
                ).fetchone()[0],
                "rubric_id": rubric["id"],
                "method": "direct",
                "assessment_tool": "Generic count assessment",
                "bloom_level": "Analyze",
                "sample_size": "10",
                "target": "70",
                "rationale": "Aligned generic evidence.",
                "observations": "Generic observation.",
                "action_notes": "Generic improvement action.",
            }
            for level, count in zip(levels, counts, strict=True):
                payload[f"level_{level['id']}"] = str(count)
            return payload

    def test_generic_form_import_template_and_export_keep_count_semantics(self) -> None:
        form = self.client.get("/assessments/new")
        fields = _named_fields(form.data)
        self.assertIn("sample_size", fields)
        self.assertTrue(any(name.startswith("level_") for name in fields))
        self.assertNotIn("expert_percent", fields)

        template = self.client.get("/import/template.csv")
        header = next(csv.reader(io.StringIO(template.text)))
        self.assertIn("sample_size", header)
        self.assertIn("Expert", header)
        self.assertNotIn("expert_percent", header)

        response = self.client.post("/assessments/new", data=self._payload((3, 5, 1, 1)))
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            record = get_db().execute(
                "SELECT result_basis,sample_size FROM assessment_records"
            ).fetchone()
            self.assertEqual(record["result_basis"], "student_counts")
            self.assertEqual(record["sample_size"], 10)

        exported = self.client.get("/export/assessments.csv")
        row = next(csv.DictReader(io.StringIO(exported.text)))
        self.assertEqual(row["sample_size"], "10")
        self.assertEqual(row["result_basis"], "student_counts")

        invalid = self.client.post(
            "/assessments/new",
            data=self._payload((3, 5, 1, 0)),
            follow_redirects=True,
        )
        self.assertEqual(invalid.status_code, 200)
        self.assertIn(b'class="flash error"', invalid.data)
        with self.app.app_context():
            self.assertEqual(
                get_db().execute("SELECT COUNT(*) FROM assessment_records").fetchone()[0],
                1,
            )


if __name__ == "__main__":
    unittest.main()
