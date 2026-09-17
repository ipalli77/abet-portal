from __future__ import annotations

import html
import tempfile
import unittest
from collections.abc import Mapping
from contextlib import contextmanager
from html.parser import HTMLParser
from pathlib import Path

from flask import template_rendered
from markupsafe import Markup
from werkzeug.security import generate_password_hash

from abet_platform import create_app
from abet_platform.db import get_db


OWNER_EMAIL = "isaac.palli@utrgv.edu"
GLOBAL_STORY_TOKENS = (
    "68%→74%",
    "+1.60pp/term",
    "65%→80%→83%",
    "61%→92%",
    "-11.03pp/term",
)
SOURCE_DOCUMENTS = (
    "SLO1_Intervention.pdf",
    "SLO2_Intervention.pdf",
    "SLO3_Intervention.pdf",
    "ABET_Criterion_4B_Revised.pdf",
    "ABET_Interventions.pdf",
    "ABET_Criterion_4C_Revised.pdf",
    "ABET_Criterion_4_2026_Isaac_Submitted.docx",
)


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def visible_text(response) -> str:
    parser = _VisibleText()
    parser.feed(response.get_data(as_text=True))
    return " ".join(" ".join(parser.parts).split())


def compact_text(response) -> str:
    return "".join(html.unescape(visible_text(response)).split()).replace("−", "-")


def nested_values(value):
    """Yield story values so a Markup object cannot bypass Jinja autoescaping."""
    yield value
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield from nested_values(key)
            yield from nested_values(item)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from nested_values(item)


@contextmanager
def captured_templates(app):
    rendered: list[tuple[str, dict]] = []

    def record(_sender, template, context, **_extra):
        rendered.append((template.name, context))

    template_rendered.connect(record, app)
    try:
        yield rendered
    finally:
        template_rendered.disconnect(record, app)


class ContinuousImprovementStoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "continuous-improvement-story-test",
                "DATABASE": str(root / "utrgv.db"),
                "UPLOAD_FOLDER": str(root / "uploads"),
                "EDITION": "utrgv_mece",
                "PRODUCT_NAME": "UTRGV ME Accreditation Hub",
                "CUSTOMER_NAME": "UTRGV Department of Mechanical Engineering",
            }
        )
        self.client = self.app.test_client()
        self._setup_owner()
        self._seed_roles_and_exact_scope()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def csrf(self) -> str:
        with self.client.session_transaction() as session:
            return session["csrf_token"]

    def _setup_owner(self) -> None:
        self.client.get("/setup")
        created = self.client.post(
            "/setup",
            data={
                "csrf_token": self.csrf(),
                "full_name": "Isaac Choutapalli",
                "email": OWNER_EMAIL,
                "password": "owner-password-long",
            },
        )
        self.assertEqual(created.status_code, 302)

    def _seed_roles_and_exact_scope(self) -> None:
        with self.app.app_context():
            db = get_db()
            program = db.execute("SELECT * FROM programs WHERE code='BSME'").fetchone()
            owner = db.execute(
                "SELECT id FROM users WHERE email=?", (OWNER_EMAIL,)
            ).fetchone()
            course_a = db.execute(
                "SELECT id FROM courses WHERE program_id=? AND code='MECE 3315'",
                (program["id"],),
            ).fetchone()[0]
            course_b = db.execute(
                "SELECT id FROM courses WHERE program_id=? AND code='MECE 2340'",
                (program["id"],),
            ).fetchone()[0]
            self.ids = {
                "organization": program["organization_id"],
                "program": program["id"],
                "owner": owner["id"],
                "course_a": course_a,
                "course_b": course_b,
            }

            for role in ("admin", "coordinator", "faculty", "reviewer", "support"):
                membership_role = "faculty" if role == "support" else role
                user_id = db.execute(
                    """INSERT INTO users
                       (email,username,full_name,password_hash)
                       VALUES (?,?,?,?)""",
                    (
                        f"story-{role}@utrgv.edu",
                        f"story-{role}",
                        f"Story {role.title()}",
                        generate_password_hash("irrelevant-test-password"),
                    ),
                ).lastrowid
                db.execute(
                    "INSERT INTO memberships(user_id,organization_id,role) VALUES (?,?,?)",
                    (user_id, program["organization_id"], membership_role),
                )
                if membership_role in {"faculty", "reviewer"}:
                    db.execute(
                        """INSERT INTO program_members(program_id,user_id,access_level)
                           VALUES (?,?,?)""",
                        (
                            program["id"],
                            user_id,
                            "viewer" if membership_role == "reviewer" else "editor",
                        ),
                    )
                    db.execute(
                        "INSERT INTO course_assignments(course_id,user_id) VALUES (?,?)",
                        (course_a, user_id),
                    )
                    db.execute(
                        """INSERT INTO course_campus_assignments
                           (course_id,user_id,campus) VALUES (?,?,'Edinburg')""",
                        (course_a, user_id),
                    )
                self.ids[role] = user_id

            db.execute(
                """INSERT INTO program_support_accounts
                   (program_id,user_id,configured_by) VALUES (?,?,?)""",
                (program["id"], self.ids["support"], owner["id"]),
            )

            term_id = db.execute(
                """SELECT id FROM academic_terms WHERE program_id=?
                   ORDER BY sort_order,id LIMIT 1""",
                (program["id"],),
            ).fetchone()[0]
            outcome_id = db.execute(
                """SELECT id FROM outcomes WHERE program_id=?
                   ORDER BY display_order,id LIMIT 1""",
                (program["id"],),
            ).fetchone()[0]
            indicator_id = db.execute(
                """SELECT id FROM performance_indicators WHERE outcome_id=?
                   ORDER BY display_order,id LIMIT 1""",
                (outcome_id,),
            ).fetchone()[0]
            rubric_id = db.execute(
                """SELECT id FROM rubrics WHERE program_id=?
                   ORDER BY is_default DESC,id LIMIT 1""",
                (program["id"],),
            ).fetchone()[0]

            scoped_records = {}
            for key, course_id, campus in (
                ("allowed", course_a, "Edinburg"),
                ("same_course_other_campus", course_a, "Brownsville"),
                ("other_course", course_b, "Edinburg"),
            ):
                scoped_records[key] = db.execute(
                    """INSERT INTO assessment_records
                       (program_id,term_id,course_id,outcome_id,indicator_id,
                        rubric_id,collected_by,campus,method,assessment_tool,
                        bloom_level,result_basis,target,status)
                       VALUES (?,?,?,?,?,?,?,?,'direct',?,'Analyze',
                               'percentages',70,'draft')""",
                    (
                        program["id"],
                        term_id,
                        course_id,
                        outcome_id,
                        indicator_id,
                        rubric_id,
                        owner["id"],
                        campus,
                        f"STORY_SCOPE_{key.upper()}",
                    ),
                ).lastrowid

            for title, record_key in (
                ("EDINBURG_ASSIGNED_ACTION", "allowed"),
                ("BROWNSVILLE_SAME_COURSE_SECRET", "same_course_other_campus"),
                ("OTHER_COURSE_SECRET", "other_course"),
            ):
                db.execute(
                    """INSERT INTO improvement_actions
                       (program_id,outcome_id,assessment_id,title,description,
                        status,created_by)
                       VALUES (?,?,?,?,?,'planned',?)""",
                    (
                        program["id"],
                        outcome_id,
                        scoped_records[record_key],
                        title,
                        f"Description for {title}",
                        owner["id"],
                    ),
                )
            db.execute(
                """INSERT INTO improvement_actions
                   (program_id,outcome_id,title,description,status,created_by)
                   VALUES (?,?, 'PROGRAMWIDE_SECRET_ACTION',
                           'Managers only', 'planned', ?)""",
                (program["id"], outcome_id, owner["id"]),
            )
            db.commit()

    def as_user(self, key: str) -> None:
        with self.client.session_transaction() as session:
            session.clear()
            session["user_id"] = self.ids[key]
            session["organization_id"] = self.ids["organization"]
            session["program_id"] = self.ids["program"]
            session["csrf_token"] = "continuous-improvement-story-csrf"

    def get_with_context(self, path: str):
        with captured_templates(self.app) as rendered:
            response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(rendered)
        return response, rendered[-1][1]

    def assert_story_evidence(self, response) -> None:
        text = visible_text(response)
        compact = compact_text(response)
        folded = text.casefold().replace("‑", "-").replace("–", "-")

        self.assertIn("criterion 4", folded)
        self.assertIn("aic", folded)
        for phase in ("analysis", "intervention", "comparison"):
            self.assertIn(phase, folded)
        for slo in ("slo-1", "slo-2", "slo-3", "slo-6"):
            self.assertIn(slo, folded)

        for token in GLOBAL_STORY_TOKENS:
            self.assertIn(token, compact)
        self.assertRegex(compact, r"PI-3(?:[:=])?60%")
        self.assertRegex(folded, r"not yet (?:been )?declared closed")

        for status in (
            "verified course-level loop",
            "positive first-term evidence",
            "monitoring continues",
            "mixed evidence",
            "adaptation required",
            "implementation complete",
            "verification in flight",
        ):
            self.assertIn(status, folded)

        self.assertIn("originally proposed", folded)
        self.assertIn("actually implemented", folded)
        for source in SOURCE_DOCUMENTS:
            self.assertIn(source, text)

    def test_utrgv_managers_receive_the_full_evidence_grounded_story(self) -> None:
        for role in ("owner", "admin", "coordinator"):
            with self.subTest(role=role):
                self.as_user(role)
                response, context = self.get_with_context("/actions")
                story = context.get("continuous_improvement_story")
                self.assertTrue(story)
                self.assert_story_evidence(response)
                self.assertFalse(
                    any(isinstance(value, Markup) for value in nested_values(story)),
                    "The story must contain plain data and rely on Jinja autoescaping.",
                )

                source = response.get_data(as_text=True)
                self.assertRegex(source, r"(?is)<table\b[^>]*>.*?<caption\b")
                self.assertRegex(source, r"(?is)<(?:thead|tbody)\b")
                self.assertRegex(source, r"(?is)<th\b")
                self.assertIn("data-print", source)
                self.assertIn("Print / save PDF", source)

    def test_restricted_identities_keep_exact_course_campus_scope_and_no_story(self) -> None:
        for role in ("faculty", "reviewer", "support"):
            for path in ("/actions", "/report"):
                with self.subTest(role=role, path=path):
                    self.as_user(role)
                    response, context = self.get_with_context(path)
                    self.assertIsNone(context.get("continuous_improvement_story"))
                    rendered = response.get_data(as_text=True)
                    compact = compact_text(response)
                    self.assertIn("EDINBURG_ASSIGNED_ACTION", rendered)
                    self.assertNotIn("BROWNSVILLE_SAME_COURSE_SECRET", rendered)
                    self.assertNotIn("OTHER_COURSE_SECRET", rendered)
                    self.assertNotIn("PROGRAMWIDE_SECRET_ACTION", rendered)
                    for token in GLOBAL_STORY_TOKENS:
                        self.assertNotIn(token, compact)

    def test_owner_report_contains_a_concise_story_but_faculty_report_does_not(self) -> None:
        self.as_user("owner")
        owner_report, owner_context = self.get_with_context("/report")
        self.assertTrue(owner_context.get("continuous_improvement_story"))
        owner_text = visible_text(owner_report).casefold()
        owner_compact = compact_text(owner_report)
        self.assertIn("criterion 4", owner_text)
        for slo in ("slo-1", "slo-2", "slo-3", "slo-6"):
            self.assertIn(slo, owner_text)
        for token in GLOBAL_STORY_TOKENS:
            self.assertIn(token, owner_compact)

        self.as_user("faculty")
        faculty_report, faculty_context = self.get_with_context("/report")
        self.assertIsNone(faculty_context.get("continuous_improvement_story"))
        faculty_compact = compact_text(faculty_report)
        for token in GLOBAL_STORY_TOKENS:
            self.assertNotIn(token, faculty_compact)

    def test_story_get_requests_do_not_change_the_database(self) -> None:
        self.as_user("owner")
        with self.app.app_context():
            before = "\n".join(get_db().iterdump())
        self.assertEqual(self.client.get("/actions").status_code, 200)
        self.assertEqual(self.client.get("/report").status_code, 200)
        with self.app.app_context():
            after = "\n".join(get_db().iterdump())
        self.assertEqual(after, before)

    def test_story_templates_do_not_disable_autoescaping(self) -> None:
        template_root = Path(self.app.root_path) / "templates"
        story_templates = []
        for template in template_root.glob("*.html"):
            source = template.read_text(encoding="utf-8")
            if "continuous_improvement_story" in source:
                story_templates.append(template.name)
                self.assertNotRegex(source, r"\|\s*safe\b")
        self.assertTrue(story_templates, "No template renders the continuous-improvement story.")


class GenericEditionStoryIsolationTests(unittest.TestCase):
    def test_generic_edition_does_not_receive_the_utrgv_criterion_4_story(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = create_app(
                {
                    "TESTING": True,
                    "SECRET_KEY": "generic-story-isolation-test",
                    "DATABASE": str(root / "generic.db"),
                    "UPLOAD_FOLDER": str(root / "uploads"),
                }
            )
            client = app.test_client()
            client.get("/setup")
            with client.session_transaction() as session:
                csrf = session["csrf_token"]
            created = client.post(
                "/setup",
                data={
                    "csrf_token": csrf,
                    "institution": "Example University",
                    "program_name": "Mechanical Engineering",
                    "program_code": "BSME",
                    "full_name": "Generic Owner",
                    "email": "owner@example.edu",
                    "password": "generic-owner-password",
                },
            )
            self.assertEqual(created.status_code, 302)
            client.get("/login")
            with client.session_transaction() as session:
                csrf = session["csrf_token"]
            logged_in = client.post(
                "/login",
                data={
                    "csrf_token": csrf,
                    "login": "owner@example.edu",
                    "password": "generic-owner-password",
                },
            )
            self.assertEqual(logged_in.status_code, 302)

            for path in ("/actions", "/report"):
                with self.subTest(path=path), captured_templates(app) as rendered:
                    response = client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(rendered)
                self.assertIsNone(
                    rendered[-1][1].get("continuous_improvement_story")
                )
                compact = compact_text(response)
                for token in GLOBAL_STORY_TOKENS:
                    self.assertNotIn(token, compact)


if __name__ == "__main__":
    unittest.main()
