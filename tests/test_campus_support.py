from __future__ import annotations

import csv
import io
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from flask import template_rendered
from werkzeug.security import generate_password_hash

from abet_platform import create_app
from abet_platform.analysis_engine import analyze_rows
from abet_platform.db import get_db


CAMPUSES = ("Edinburg", "Brownsville")


@contextmanager
def captured_templates(app):
    rendered = []

    def record(_sender, template, context, **_extra):
        rendered.append((template, context))

    template_rendered.connect(record, app)
    try:
        yield rendered
    finally:
        template_rendered.disconnect(record, app)


class UtrgvCampusSupportTests(unittest.TestCase):
    """End-to-end contract for the two-campus UTRGV edition."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "campus-test-secret",
                "DATABASE": str(root / "utrgv-campus.db"),
                "UPLOAD_FOLDER": str(root / "uploads"),
                "EDITION": "utrgv_mece",
                "PRODUCT_NAME": "UTRGV ME Accreditation Hub",
                "CUSTOMER_NAME": "UTRGV Department of Mechanical Engineering",
                "LEGACY_DATABASE": str(root / "missing-legacy.db"),
            }
        )
        self.client = self.app.test_client()
        self._bootstrap_owner()
        self.ids = self._dimensions_and_users()

    def tearDown(self):
        self.temp.cleanup()

    def csrf(self):
        with self.client.session_transaction() as session:
            return session["csrf_token"]

    def _bootstrap_owner(self):
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
        self._login("isaac.palli@utrgv.edu", "owner-password-long")

    def _dimensions_and_users(self):
        with self.app.app_context():
            db = get_db()
            program = db.execute("SELECT * FROM programs WHERE code='BSME'").fetchone()
            organization_id = program["organization_id"]
            owner_id = db.execute(
                "SELECT id FROM users WHERE email='isaac.palli@utrgv.edu'"
            ).fetchone()[0]
            term_id = db.execute(
                "SELECT id FROM academic_terms WHERE program_id=? ORDER BY sort_order DESC LIMIT 1",
                (program["id"],),
            ).fetchone()[0]
            outcome_id = db.execute(
                "SELECT id FROM outcomes WHERE program_id=? ORDER BY display_order,id LIMIT 1",
                (program["id"],),
            ).fetchone()[0]
            indicator_id = db.execute(
                "SELECT id FROM performance_indicators WHERE outcome_id=? ORDER BY display_order,id LIMIT 1",
                (outcome_id,),
            ).fetchone()[0]
            rubric_id = db.execute(
                "SELECT id FROM rubrics WHERE program_id=? ORDER BY is_default DESC,id LIMIT 1",
                (program["id"],),
            ).fetchone()[0]
            levels = db.execute(
                "SELECT id,is_attained FROM rubric_levels WHERE rubric_id=? ORDER BY display_order,id",
                (rubric_id,),
            ).fetchall()
            course_ids = {
                row["code"]: row["id"]
                for row in db.execute(
                    "SELECT id,code FROM courses WHERE program_id=? AND code IN ('MECE 3315','MECE 3320')",
                    (program["id"],),
                )
            }

            admin_id = db.execute(
                "INSERT INTO users(email,full_name,password_hash) VALUES (?,?,?)",
                (
                    "admin@example.edu",
                    "ABET Administrator",
                    generate_password_hash("admin-password-long"),
                ),
            ).lastrowid
            faculty_id = db.execute(
                "INSERT INTO users(email,full_name,password_hash) VALUES (?,?,?)",
                (
                    "assigned.faculty@utrgv.edu",
                    "Assigned Faculty",
                    generate_password_hash("faculty-password-long"),
                ),
            ).lastrowid
            db.executemany(
                "INSERT INTO memberships(user_id,organization_id,role) VALUES (?,?,?)",
                (
                    (admin_id, organization_id, "admin"),
                    (faculty_id, organization_id, "faculty"),
                ),
            )
            db.executemany(
                "INSERT INTO program_members(program_id,user_id,access_level) VALUES (?,?,?)",
                (
                    (program["id"], admin_id, "manager"),
                    (program["id"], faculty_id, "editor"),
                ),
            )
            db.execute(
                "INSERT INTO course_assignments(course_id,user_id) VALUES (?,?)",
                (course_ids["MECE 3320"], faculty_id),
            )
            db.executemany(
                """INSERT INTO course_campus_assignments
                   (course_id,user_id,campus) VALUES (?,?,?)""",
                [
                    (course_ids["MECE 3320"], faculty_id, campus)
                    for campus in CAMPUSES
                ],
            )
            roster_id = db.execute(
                """INSERT INTO faculty_roster
                   (program_id,legacy_name,display_name,approved_email,user_id,status)
                   VALUES (?,?,?,?,?,'active')""",
                (
                    program["id"],
                    "Assigned Faculty",
                    "Assigned Faculty",
                    "assigned.faculty@utrgv.edu",
                    faculty_id,
                ),
            ).lastrowid
            db.execute(
                """INSERT INTO faculty_roster_courses
                   (faculty_roster_id,course_id) VALUES (?,?)""",
                (roster_id, course_ids["MECE 3320"]),
            )
            db.executemany(
                """INSERT INTO faculty_roster_course_campuses
                   (faculty_roster_id,course_id,campus) VALUES (?,?,?)""",
                [
                    (roster_id, course_ids["MECE 3320"], campus)
                    for campus in CAMPUSES
                ],
            )
            db.commit()
            return {
                "organization": organization_id,
                "program": program["id"],
                "owner": owner_id,
                "admin": admin_id,
                "faculty": faculty_id,
                "term": term_id,
                "outcome": outcome_id,
                "indicator": indicator_id,
                "rubric": rubric_id,
                "levels": levels,
                "courses": course_ids,
            }

    def _login(self, login, password):
        with self.client.session_transaction() as session:
            session.clear()
        self.client.get("/login")
        response = self.client.post(
            "/login",
            data={"csrf_token": self.csrf(), "login": login, "password": password},
        )
        self.assertEqual(response.status_code, 302)
        return response

    def _assessment_payload(
        self,
        *,
        campus: str | None,
        course_code: str = "MECE 3320",
        tool: str = "Campus assessment",
        observations: str = "Assessment interpretation.",
    ):
        payload = {
            "csrf_token": self.csrf(),
            "term_id": str(self.ids["term"]),
            "course_id": str(self.ids["courses"][course_code]),
            "outcome_id": str(self.ids["outcome"]),
            "indicator_id": str(self.ids["indicator"]),
            "rubric_id": str(self.ids["rubric"]),
            "method": "direct",
            "assessment_tool": tool,
            "bloom_level": "Analyze",
            "target": "70",
            "expert_percent": "30",
            "practitioner_percent": "50",
            "apprentice_percent": "10",
            "novice_percent": "10",
            "rationale": "The measure is aligned to the selected indicator.",
            "observations": observations,
            "action_notes": "Review this result in the next faculty meeting.",
        }
        if campus is not None:
            payload["campus"] = campus
        return payload

    def _insert_record(
        self,
        *,
        campus: str,
        course_code: str,
        attainment: int,
        target: float,
        collector_id: int | None = None,
        tool: str,
        status: str = "approved",
    ) -> int:
        with self.app.app_context():
            db = get_db()
            record_id = db.execute(
                """INSERT INTO assessment_records
                   (program_id,term_id,course_id,outcome_id,indicator_id,rubric_id,
                    collected_by,campus,method,assessment_tool,bloom_level,sample_size,
                    target,status)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.ids["program"],
                    self.ids["term"],
                    self.ids["courses"][course_code],
                    self.ids["outcome"],
                    self.ids["indicator"],
                    self.ids["rubric"],
                    collector_id or self.ids["owner"],
                    campus,
                    "direct",
                    tool,
                    "Analyze",
                    100,
                    target,
                    status,
                ),
            ).lastrowid
            attained_level = next(level["id"] for level in self.ids["levels"] if level["is_attained"])
            not_attained_level = next(
                level["id"] for level in self.ids["levels"] if not level["is_attained"]
            )
            counts = {attained_level: attainment, not_attained_level: 100 - attainment}
            db.executemany(
                "INSERT INTO assessment_results(assessment_id,rubric_level_id,student_count) VALUES (?,?,?)",
                [
                    (record_id, level["id"], counts.get(level["id"], 0))
                    for level in self.ids["levels"]
                ],
            )
            db.commit()
            return record_id

    def _analytics_context(self, query_string=None):
        with captured_templates(self.app) as rendered:
            response = self.client.get("/analytics", query_string=query_string)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(rendered)
        self.assertEqual(rendered[-1][0].name, "analytics.html")
        return response, rendered[-1][1]

    def _seed_comparison_records(self):
        return {
            "edinburg_high": self._insert_record(
                campus="Edinburg",
                course_code="MECE 3320",
                attainment=80,
                target=75,
                tool="Edinburg measure A",
            ),
            "edinburg_low": self._insert_record(
                campus="Edinburg",
                course_code="MECE 3320",
                attainment=60,
                target=50,
                tool="Edinburg measure B",
            ),
            "brownsville_low": self._insert_record(
                campus="Brownsville",
                course_code="MECE 3315",
                attainment=78,
                target=80,
                tool="Brownsville measure A",
            ),
            "brownsville_high": self._insert_record(
                campus="Brownsville",
                course_code="MECE 3315",
                attainment=88,
                target=85,
                tool="Brownsville measure B",
            ),
        }

    def test_assessment_campus_is_required_and_limited_to_utrgv_campuses(self):
        with self.app.app_context():
            campus_column = {
                row["name"]: row for row in get_db().execute("PRAGMA table_info(assessment_records)")
            }["campus"]
            self.assertEqual(campus_column["notnull"], 1)

        form = self.client.get("/assessments/new")
        self.assertEqual(form.status_code, 200)
        self.assertIn(b'name="campus"', form.data)
        self.assertIn(b"Edinburg", form.data)
        self.assertIn(b"Brownsville", form.data)

        with self.app.app_context():
            count_before = get_db().execute("SELECT COUNT(*) FROM assessment_records").fetchone()[0]
        missing = self.client.post(
            "/assessments/new", data=self._assessment_payload(campus=None, tool="Missing campus")
        )
        self.assertEqual(missing.status_code, 200)
        self.assertIn(b"Campus is required", missing.data)
        invalid = self.client.post(
            "/assessments/new",
            data=self._assessment_payload(campus="Harlingen", tool="Invalid campus"),
        )
        self.assertEqual(invalid.status_code, 200)
        self.assertIn(b"Edinburg or Brownsville", invalid.data)
        with self.app.app_context():
            self.assertEqual(
                get_db().execute("SELECT COUNT(*) FROM assessment_records").fetchone()[0],
                count_before,
            )

        valid = self.client.post(
            "/assessments/new",
            data=self._assessment_payload(campus="Brownsville", tool="Valid campus"),
        )
        self.assertEqual(valid.status_code, 302)
        with self.app.app_context():
            campus = get_db().execute(
                "SELECT campus FROM assessment_records WHERE assessment_tool='Valid campus'"
            ).fetchone()[0]
            self.assertEqual(campus, "Brownsville")

    def test_faculty_can_create_and_edit_own_assigned_course_draft_with_campus(self):
        owner_record = self._insert_record(
            campus="Edinburg",
            course_code="MECE 3320",
            attainment=75,
            target=70,
            tool="Owner record in assigned course",
            status="draft",
        )
        self._login("assigned.faculty@utrgv.edu", "faculty-password-long")

        created = self.client.post(
            "/assessments/new",
            data=self._assessment_payload(
                campus="Edinburg",
                tool="Faculty campus draft",
                observations="Initial interpretation.",
            ),
        )
        self.assertEqual(created.status_code, 302)
        with self.app.app_context():
            record = get_db().execute(
                """SELECT id,collected_by,campus,status,record_version FROM assessment_records
                   WHERE assessment_tool='Faculty campus draft'"""
            ).fetchone()
            self.assertEqual(record["collected_by"], self.ids["faculty"])
            self.assertEqual(record["campus"], "Edinburg")
            self.assertEqual(record["status"], "draft")

        edit_payload = self._assessment_payload(
            campus="Brownsville",
            tool="Faculty campus draft",
            observations="Corrected campus and interpretation.",
        )
        edit_payload["record_version"] = str(record["record_version"])
        edited = self.client.post(
            f"/assessments/{record['id']}/edit",
            data=edit_payload,
        )
        self.assertEqual(edited.status_code, 302)
        with self.app.app_context():
            updated = get_db().execute(
                "SELECT campus,observations FROM assessment_records WHERE id=?", (record["id"],)
            ).fetchone()
            self.assertEqual(updated["campus"], "Brownsville")
            self.assertEqual(updated["observations"], "Corrected campus and interpretation.")

        self.assertEqual(
            self.client.post(
                "/assessments/new",
                data=self._assessment_payload(
                    campus="Edinburg",
                    course_code="MECE 3315",
                    tool="Unassigned campus record",
                ),
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                f"/assessments/{owner_record}/edit",
                data=self._assessment_payload(campus="Brownsville", tool="Ownership bypass"),
            ).status_code,
            403,
        )

    def test_admin_sees_all_campuses_while_faculty_remains_course_scoped(self):
        self._seed_comparison_records()
        self._login("admin@example.edu", "admin-password-long")

        listing = self.client.get("/assessments")
        self.assertEqual(listing.status_code, 200)
        for text in (b"Edinburg", b"Brownsville", b"Edinburg measure A", b"Brownsville measure A"):
            self.assertIn(text, listing.data)
        _response, admin_context = self._analytics_context()
        self.assertEqual(len(admin_context["records"]), 4)
        self.assertEqual({row["campus"] for row in admin_context["records"]}, set(CAMPUSES))

        self._login("assigned.faculty@utrgv.edu", "faculty-password-long")
        faculty_listing = self.client.get("/assessments")
        self.assertEqual(faculty_listing.status_code, 200)
        self.assertIn(b"Edinburg measure A", faculty_listing.data)
        self.assertNotIn(b"Brownsville measure A", faculty_listing.data)
        _response, faculty_context = self._analytics_context()
        self.assertEqual(
            {row["course_id"] for row in faculty_context["records"]},
            {self.ids["courses"]["MECE 3320"]},
        )
        self.assertEqual(
            self.client.get(
                "/analytics",
                query_string={
                    "course_id": self.ids["courses"]["MECE 3315"],
                    "campus": "Brownsville",
                },
            ).status_code,
            403,
        )

    def test_faculty_course_campus_pairs_do_not_form_a_cartesian_scope(self):
        course_a = self.ids["courses"]["MECE 3320"]
        course_b = self.ids["courses"]["MECE 3315"]
        with self.app.app_context():
            db = get_db()
            roster_id = db.execute(
                "SELECT id FROM faculty_roster WHERE user_id=?",
                (self.ids["faculty"],),
            ).fetchone()[0]
            db.execute(
                "DELETE FROM course_campus_assignments WHERE user_id=?",
                (self.ids["faculty"],),
            )
            db.executemany(
                """INSERT INTO course_campus_assignments
                   (course_id,user_id,campus) VALUES (?,?,?)""",
                [
                    (course_a, self.ids["faculty"], "Edinburg"),
                    (course_b, self.ids["faculty"], "Brownsville"),
                ],
            )
            db.execute(
                "INSERT OR IGNORE INTO course_assignments(course_id,user_id) VALUES (?,?)",
                (course_b, self.ids["faculty"]),
            )
            db.execute(
                "DELETE FROM faculty_roster_course_campuses WHERE faculty_roster_id=?",
                (roster_id,),
            )
            db.executemany(
                """INSERT INTO faculty_roster_course_campuses
                   (faculty_roster_id,course_id,campus) VALUES (?,?,?)""",
                [
                    (roster_id, course_a, "Edinburg"),
                    (roster_id, course_b, "Brownsville"),
                ],
            )
            db.execute(
                """INSERT OR IGNORE INTO faculty_roster_courses
                   (faculty_roster_id,course_id) VALUES (?,?)""",
                (roster_id, course_b),
            )
            db.commit()

        records = {
            "a_e": self._insert_record(
                campus="Edinburg", course_code="MECE 3320", attainment=81,
                target=70, tool="Allowed A Edinburg",
            ),
            "a_b": self._insert_record(
                campus="Brownsville", course_code="MECE 3320", attainment=82,
                target=70, tool="Forbidden A Brownsville",
            ),
            "b_e": self._insert_record(
                campus="Edinburg", course_code="MECE 3315", attainment=83,
                target=70, tool="Forbidden B Edinburg",
            ),
            "b_b": self._insert_record(
                campus="Brownsville", course_code="MECE 3315", attainment=84,
                target=70, tool="Allowed B Brownsville",
            ),
        }
        self._login("assigned.faculty@utrgv.edu", "faculty-password-long")

        listing = self.client.get("/assessments")
        self.assertIn(b"Allowed A Edinburg", listing.data)
        self.assertIn(b"Allowed B Brownsville", listing.data)
        self.assertNotIn(b"Forbidden A Brownsville", listing.data)
        self.assertNotIn(b"Forbidden B Edinburg", listing.data)
        _response, context = self._analytics_context({"evidence_scope": "all"})
        self.assertEqual(
            {(row["course_id"], row["campus"]) for row in context["records"]},
            {(course_a, "Edinburg"), (course_b, "Brownsville")},
        )
        exported = self.client.get(
            "/export/assessments.csv", query_string={"evidence_scope": "all"}
        )
        exported_tools = {
            row["assessment_tool"]
            for row in csv.DictReader(io.StringIO(exported.text))
        }
        self.assertEqual(
            exported_tools,
            {"Allowed A Edinburg", "Allowed B Brownsville"},
        )
        self.assertEqual(
            self.client.get(f"/assessments/{records['a_e']}/edit").status_code,
            200,
        )
        self.assertEqual(
            self.client.get(f"/assessments/{records['b_b']}/edit").status_code,
            200,
        )
        self.assertEqual(
            self.client.get(f"/assessments/{records['a_b']}/edit").status_code,
            403,
        )
        self.assertEqual(
            self.client.get(f"/assessments/{records['b_e']}/edit").status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                "/assessments/new",
                data=self._assessment_payload(
                    campus="Brownsville",
                    course_code="MECE 3320",
                    tool="Cartesian bypass attempt",
                ),
            ).status_code,
            403,
        )

        self._login("isaac.palli@utrgv.edu", "owner-password-long")
        owner_listing = self.client.get("/assessments")
        for tool in (
            b"Allowed A Edinburg",
            b"Forbidden A Brownsville",
            b"Forbidden B Edinburg",
            b"Allowed B Brownsville",
        ):
            self.assertIn(tool, owner_listing.data)

    def test_owner_pair_update_immediately_rescopes_an_active_faculty_account(self):
        course_id = self.ids["courses"]["MECE 3320"]
        with self.app.app_context():
            roster_id = get_db().execute(
                "SELECT id FROM faculty_roster WHERE user_id=?",
                (self.ids["faculty"],),
            ).fetchone()[0]
        response = self.client.post(
            f"/utrgv/faculty/{roster_id}/invitation",
            data={
                "csrf_token": self.csrf(),
                "display_name": "Assigned Faculty",
                "approved_email": "assigned.faculty@utrgv.edu",
                "course_campus_pairs": f"{course_id}:Edinburg",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            db = get_db()
            active_pairs = {
                (row["course_id"], row["campus"])
                for row in db.execute(
                    """SELECT course_id,campus FROM course_campus_assignments
                       WHERE user_id=?""",
                    (self.ids["faculty"],),
                )
            }
            roster_pairs = {
                (row["course_id"], row["campus"])
                for row in db.execute(
                    """SELECT course_id,campus FROM faculty_roster_course_campuses
                       WHERE faculty_roster_id=?""",
                    (roster_id,),
                )
            }
            self.assertEqual(active_pairs, {(course_id, "Edinburg")})
            self.assertEqual(roster_pairs, active_pairs)

        self._login("assigned.faculty@utrgv.edu", "faculty-password-long")
        form = self.client.get("/assessments/new")
        self.assertIn(b'<option value="Edinburg"', form.data)
        self.assertNotIn(b'<option value="Brownsville"', form.data)
        self.assertEqual(
            self.client.post(
                "/assessments/new",
                data=self._assessment_payload(
                    campus="Brownsville", tool="Revoked campus attempt"
                ),
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                "/assessments/new",
                data=self._assessment_payload(
                    campus="Edinburg", tool="Allowed after rescope"
                ),
            ).status_code,
            302,
        )

    def test_v11_backfill_is_idempotent_and_preserves_existing_course_access(self):
        with self.app.app_context():
            db = get_db()
            roster_course_count = db.execute(
                "SELECT COUNT(*) FROM faculty_roster_courses"
            ).fetchone()[0]
            active_course_count = db.execute(
                "SELECT COUNT(*) FROM course_assignments"
            ).fetchone()[0]
            db.execute("DELETE FROM faculty_roster_course_campuses")
            db.execute("DELETE FROM course_campus_assignments")
            db.execute("DELETE FROM schema_versions WHERE version=11")
            db.commit()

        config = {
            "TESTING": True,
            "SECRET_KEY": "campus-migration-secret",
            "DATABASE": self.app.config["DATABASE"],
            "UPLOAD_FOLDER": self.app.config["UPLOAD_FOLDER"],
            "EDITION": "utrgv_mece",
            "PRODUCT_NAME": "UTRGV ME Accreditation Hub",
            "CUSTOMER_NAME": "UTRGV Department of Mechanical Engineering",
            "LEGACY_DATABASE": self.app.config.get("LEGACY_DATABASE", ""),
        }
        migrated_app = create_app(config)
        with migrated_app.app_context():
            db = get_db()
            self.assertIsNotNone(
                db.execute(
                    "SELECT 1 FROM schema_versions WHERE version=11"
                ).fetchone()
            )
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM faculty_roster_course_campuses"
                ).fetchone()[0],
                roster_course_count * 2,
            )
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM course_campus_assignments"
                ).fetchone()[0],
                active_course_count * 2,
            )
            first_counts = (
                db.execute(
                    "SELECT COUNT(*) FROM faculty_roster_course_campuses"
                ).fetchone()[0],
                db.execute(
                    "SELECT COUNT(*) FROM course_campus_assignments"
                ).fetchone()[0],
            )

        restarted_app = create_app(config)
        with restarted_app.app_context():
            db = get_db()
            self.assertEqual(
                (
                    db.execute(
                        "SELECT COUNT(*) FROM faculty_roster_course_campuses"
                    ).fetchone()[0],
                    db.execute(
                        "SELECT COUNT(*) FROM course_campus_assignments"
                    ).fetchone()[0],
                ),
                first_counts,
            )

    def test_analytics_filters_one_or_both_campuses_and_compares_targets_exactly(self):
        self._seed_comparison_records()
        _response, both = self._analytics_context(
            [("campus", "Edinburg"), ("campus", "Brownsville")]
        )
        self.assertEqual(both["selected_campuses"], set(CAMPUSES))
        self.assertEqual(len(both["records"]), 4)

        summaries = {item["label"]: item for item in both["analysis"]["campuses"]}
        self.assertEqual(set(summaries), set(CAMPUSES))
        self.assertEqual(summaries["Edinburg"]["count"], 2)
        self.assertAlmostEqual(summaries["Edinburg"]["mean"], 70.0)
        self.assertAlmostEqual(summaries["Edinburg"]["target"], 62.5)
        self.assertAlmostEqual(summaries["Edinburg"]["target_gap"], 7.5)
        self.assertEqual(summaries["Edinburg"]["met_count"], 2)
        self.assertAlmostEqual(summaries["Edinburg"]["met_rate"], 100.0)
        self.assertEqual(summaries["Brownsville"]["count"], 2)
        self.assertAlmostEqual(summaries["Brownsville"]["mean"], 83.0)
        self.assertAlmostEqual(summaries["Brownsville"]["target"], 82.5)
        self.assertAlmostEqual(summaries["Brownsville"]["target_gap"], 0.5)
        self.assertEqual(summaries["Brownsville"]["met_count"], 1)
        self.assertAlmostEqual(summaries["Brownsville"]["met_rate"], 50.0)

        comparison = both["analysis"]["campus_comparison"]
        self.assertEqual(comparison["status"], "available")
        self.assertEqual(comparison["difference_direction"], "Brownsville minus Edinburg")
        self.assertAlmostEqual(comparison["attainment_difference"], 13.0)
        self.assertAlmostEqual(comparison["target_gap_difference"], -7.0)
        self.assertAlmostEqual(comparison["met_rate_difference"], -50.0)
        self.assertEqual(comparison["higher_attainment_campus"], "Brownsville")
        self.assertEqual(comparison["stronger_target_adjusted_campus"], "Edinburg")
        self.assertEqual(both["analysis"]["methodology"]["unit"], "assessment measure")
        self.assertEqual(
            both["analysis"]["methodology"]["campus_comparison"],
            "unweighted assessment measures using each measure's configured target",
        )

        _campus_response, campus_view = self._analytics_context({"view": "campus"})
        chart = campus_view["charts"]["campus_comparison"]
        self.assertTrue(chart["available"])
        self.assertEqual(chart["chart_type"], "campus_comparison")
        self.assertIn("Edinburg", chart["alt_text"])
        self.assertIn("Brownsville", chart["alt_text"])
        self.assertIn("target", chart["alt_text"].lower())
        trend_chart = both["charts"]["trend_line"]
        self.assertTrue(trend_chart["available"])
        self.assertEqual(
            [
                item["campus"]
                for item in trend_chart["metadata"]["campus_series"]
            ],
            ["Edinburg", "Brownsville"],
        )

        _response, edinburg = self._analytics_context({"campus": "Edinburg"})
        self.assertEqual(edinburg["selected_campuses"], {"Edinburg"})
        self.assertEqual(len(edinburg["records"]), 2)
        self.assertEqual({row["campus"] for row in edinburg["records"]}, {"Edinburg"})
        edinburg_trend = edinburg["charts"]["trend_line"]
        self.assertTrue(edinburg_trend["available"])
        self.assertEqual(
            [
                item["campus"]
                for item in edinburg_trend["metadata"]["campus_series"]
            ],
            ["Edinburg"],
        )
        self.assertNotIn("Brownsville", edinburg_trend["alt_text"])
        self.assertEqual(
            self.client.get("/analytics?campus=Harlingen").status_code,
            400,
        )
        self.assertEqual(
            self.client.get("/analytics?campus_selection=explicit").status_code,
            400,
        )

    def test_campus_comparison_has_a_clear_sparse_data_state(self):
        rows = [
            {
                "id": 1,
                "status": "approved",
                "campus": "Edinburg",
                "course_id": 10,
                "course_code": "MECE 3320",
                "course_label": "MECE 3320 — Measurements & Instrumentation",
                "term_id": 20,
                "term_label": "Fall 2025",
                "term_order": 20,
                "outcome_id": 30,
                "outcome_code": "SLO1",
                "outcome_label": "SLO1: Engineering problems",
                "outcome_order": 1,
                "indicator_id": 40,
                "indicator_code": "PI-1",
                "indicator_label": "PI-1: Apply mathematics",
                "bloom_level": "Apply",
                "attainment": 76.0,
                "target": 70.0,
            }
        ]
        analysis = analyze_rows(rows)
        self.assertEqual([item["label"] for item in analysis["campuses"]], ["Edinburg"])
        comparison = analysis["campus_comparison"]
        self.assertEqual(comparison["status"], "unavailable")
        self.assertIsNone(comparison["attainment_difference"])
        self.assertIn("Edinburg", comparison["reason"])
        self.assertIn("Brownsville", comparison["reason"])
        self.assertIn("at least one", comparison["reason"].lower())

        self._insert_record(
            campus="Edinburg",
            course_code="MECE 3320",
            attainment=76,
            target=70,
            tool="Only one campus",
        )
        response, context = self._analytics_context({"campus": "Edinburg", "view": "campus"})
        chart = context["charts"]["campus_comparison"]
        self.assertFalse(chart["available"])
        self.assertIn("Brownsville", chart["reason"])
        self.assertIn(chart["reason"].encode(), response.data)

    def test_csv_export_preserves_campus_and_honors_the_campus_filter(self):
        self._seed_comparison_records()
        all_export = self.client.get("/export/assessments.csv?evidence_scope=approved")
        self.assertEqual(all_export.status_code, 200)
        all_rows = list(csv.DictReader(io.StringIO(all_export.text)))
        self.assertEqual(set(CAMPUSES), {row["campus"] for row in all_rows})
        self.assertIn("campus", all_rows[0])

        filtered_export = self.client.get(
            "/export/assessments.csv",
            query_string={"evidence_scope": "approved", "campus": "Brownsville"},
        )
        self.assertEqual(filtered_export.status_code, 200)
        filtered_rows = list(csv.DictReader(io.StringIO(filtered_export.text)))
        self.assertEqual(len(filtered_rows), 2)
        self.assertEqual({row["campus"] for row in filtered_rows}, {"Brownsville"})
        self.assertEqual(
            {row["assessment_tool"] for row in filtered_rows},
            {"Brownsville measure A", "Brownsville measure B"},
        )


if __name__ == "__main__":
    unittest.main()
