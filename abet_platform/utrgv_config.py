"""Customer profile and idempotent seed data for UTRGV Mechanical Engineering."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


ORGANIZATION_NAME = "The University of Texas Rio Grande Valley"
PROGRAM_NAME = "Mechanical Engineering"
PROGRAM_CODE = "BSME"
PRIMARY_COLOR = "#003638"
ACCENT_COLOR = "#ee7f2f"
CAMPUS_NAMES: Sequence[str] = ("Edinburg", "Brownsville")
OWNER_NAME = "Isaac Choutapalli"
OWNER_EMAIL = "isaac.palli@utrgv.edu"

COURSES: Sequence[tuple[str, str]] = (
    ("MECE 1101", "Intro to ME"),
    ("MECE 1221", "Engineering Graphics"),
    ("MECE 2140", "Engineering Materials Lab"),
    ("MECE 2302", "Dynamics"),
    ("MECE 2340", "Engineering Materials"),
    ("MECE 3170", "Thermal Fluids Laboratory"),
    ("MECE 3315", "Fluid Mechanics"),
    ("MECE 3320", "Measurements & Instrumentation"),
    ("MECE 3336", "Thermodynamics II"),
    ("MECE 3360", "Heat Transfer"),
    ("MECE 3380", "Kinematics & Dynamics of Machines"),
    ("MECE 3450", "Mechanical Engineering Analysis II"),
    ("MECE 4350", "Machine Elements"),
    ("MECE 4361", "Senior Design-I"),
    ("MECE 4362", "Senior Design-II"),
    ("PHIL 2393", "Philosophy"),
)


@dataclass(frozen=True)
class FacultyRosterEntry:
    """An approved UTRGV faculty identity and its initial course scope.

    ``aliases`` retain the abbreviated names used by earlier versions of the
    UTRGV edition.  They are migration identifiers only; new accounts use the
    canonical display name and institutional email.
    """

    display_name: str
    approved_email: str
    course_codes: tuple[str, ...]
    aliases: tuple[str, ...] = ()


FACULTY_ROSTER: tuple[FacultyRosterEntry, ...] = (
    FacultyRosterEntry("Yingchen Yang", "yingchen.yang@utrgv.edu", ("MECE 1101",)),
    FacultyRosterEntry("Lawrence Cano", "lawrence.cano@utrgv.edu", ("MECE 1221",)),
    FacultyRosterEntry(
        "Misael Martinez", "misael.e.martinez01@utrgv.edu", ("MECE 2140",)
    ),
    FacultyRosterEntry(
        "Eleazar Marquez",
        "eleazar.marquez01@utrgv.edu",
        ("MECE 2302", "MECE 4362"),
    ),
    FacultyRosterEntry("Robert Jones", "robert.jones@utrgv.edu", ("MECE 2340",)),
    FacultyRosterEntry(
        "Jose Sanchez",
        "jose.j.sanchez01@utrgv.edu",
        ("MECE 3170", "MECE 3336"),
    ),
    FacultyRosterEntry("Nadim Zgheib", "nadim.zgheib@utrgv.edu", ("MECE 3315",)),
    FacultyRosterEntry(
        "Constantine Tarawneh",
        "constantine.tarawneh@utrgv.edu",
        ("MECE 3360",),
        aliases=("Constantine T",),
    ),
    FacultyRosterEntry(
        "Robert Freeman", "robert.freeman@utrgv.edu", ("MECE 3380",)
    ),
    FacultyRosterEntry(
        "Dumitru Caruntu",
        "dumitru.caruntu@utrgv.edu",
        ("MECE 3450",),
        aliases=("Caruntu D",),
    ),
    FacultyRosterEntry("Javier Ortega", "javier.ortega@utrgv.edu", ("MECE 4350",)),
    FacultyRosterEntry("Noe Vargas", "noe.vargas@utrgv.edu", ("MECE 4361",)),
    FacultyRosterEntry(
        "Mataz Alcoutlabi", "mataz.alcoutlabi@utrgv.edu", ("PHIL 2393",)
    ),
)

# Backwards-compatible name/course view for callers that used the original
# customer configuration constant.  New code should prefer ``FACULTY_ROSTER``
# because it also carries the approved email and historical aliases.
FACULTY_COURSES: Sequence[tuple[str, Sequence[str]]] = tuple(
    (entry.display_name, entry.course_codes) for entry in FACULTY_ROSTER
)

# These identities existed only in the superseded built-in roster.  Restrict
# cleanup to this explicit list so an owner-approved invitation added later is
# never removed by an idempotent repair.
OBSOLETE_SEEDED_FACULTY: tuple[str, ...] = (
    "Isaac Choutapalli",
    "Kamal Sarkar",
)

TERMS: Sequence[str] = (
    "Fall 2020", "Spring 2021", "Fall 2021", "Spring 2022", "Fall 2022",
    "Spring 2023", "Fall 2023", "Spring 2024", "Fall 2024", "Spring 2025",
    "Fall 2025", "Spring 2026", "Fall 2026",
)

OUTCOMES: Sequence[tuple[str, str]] = (
    ("SLO1", "An ability to identify, formulate, and solve complex engineering problems by applying principles of engineering, science, and mathematics."),
    ("SLO2", "An ability to apply engineering design to produce solutions that meet specified needs with consideration of public health, safety, and welfare, as well as global, cultural, social, environmental, and economic factors."),
    ("SLO3", "An ability to communicate effectively with a range of audiences."),
    ("SLO4", "An ability to recognize ethical and professional responsibilities in engineering situations and make informed judgments, which must consider the impact of engineering solutions in global, economic, environmental, and societal contexts."),
    ("SLO5", "An ability to function effectively on a team whose members together provide leadership, create a collaborative and inclusive environment, establish goals, plan tasks, and meet objectives."),
    ("SLO6", "An ability to develop and conduct appropriate experimentation, analyze and interpret data, and use engineering judgement to draw conclusions."),
    ("SLO7", "An ability to acquire and apply new knowledge as needed, using appropriate learning strategies."),
)

INDICATORS: dict[str, Sequence[tuple[str, str]]] = {
    "SLO1": (
        ("PI-1", "Able to Identify engineering problem"),
        ("PI-2", "Able to formulate a problem"),
        ("PI-3", "Able to solve Problem"),
    ),
    "SLO2": (
        ("PI-1", "Able to design a system, component, or process"),
        ("PI-2", "Able to design to meet desired needs"),
        ("PI-3", "Able to design within realistic constraints"),
    ),
    "SLO3": (
        ("PI-1", "Generate appropriate graphics"),
        ("PI-2", "Demonstrates adequate presentation skills"),
        ("PI-3", "Applies technical writing skills"),
        ("PI-4", "Contextualizes communication for intended audience"),
    ),
    "SLO4": (
        ("PI-1", "Recognize ethical and professional responsibilities in engineering situations"),
        ("PI-2", "Make informed ethical and professional judgments"),
        ("PI-3", "Consider the impact of engineering solutions in global, economic, environmental, and societal contexts"),
    ),
    "SLO5": (
        ("PI-1", "Establish goals"),
        ("PI-2", "Plan tasks & meet deadlines"),
        ("PI-3", "Fulfill duties of team roles"),
        ("PI-4", "Shares work equally"),
        ("PI-5", "Communicates effectively in a team setting"),
        ("PI-6", "Proficient in all aspects of the project"),
    ),
    "SLO6": (
        ("PI-1", "Develops and conducts appropriate experimentation"),
        ("PI-2", "Analyzes and interprets data"),
        ("PI-3", "Evaluates appropriate findings to draw conclusions"),
    ),
    "SLO7": (
        ("PI-1", "Recognize the ongoing need to acquire new knowledge"),
        ("PI-2", "Choose appropriate learning strategies to acquire new knowledge"),
        ("PI-3", "Apply new knowledge appropriately"),
    ),
}

# The legacy database contains these older SLO5 meanings. They remain distinct
# indicators so imported evidence is never silently relabeled.
HISTORICAL_INDICATORS: Sequence[tuple[str, str, str]] = (
    ("SLO5", "PI-3-H", "Provides leadership within the team"),
    ("SLO5", "PI-4-H", "Creates a collaborative and inclusive environment"),
    ("SLO5", "PI-6-H", "Meets objectives"),
)


def _term_order(name: str) -> int:
    season, year = name.split()
    return int(year) * 10 + (1 if season == "Spring" else 2)


def seed_utrgv_faculty_roster(db, program_id: int) -> None:
    """Synchronize approved identities and initial two-campus course access.

    The operation is idempotent and deliberately preserves an already linked
    user account.  Historical abbreviated roster names are folded into their
    canonical identity.  Obsolete, never-activated seed rows are removed;
    linked rows are retained as inactive provenance with no course-campus access.
    """
    canonical_names = {entry.display_name.casefold() for entry in FACULTY_ROSTER}
    approved_emails = {entry.approved_email.casefold() for entry in FACULTY_ROSTER}
    if len(canonical_names) != len(FACULTY_ROSTER):
        raise ValueError("The UTRGV faculty roster contains a duplicate name.")
    if len(approved_emails) != len(FACULTY_ROSTER):
        raise ValueError("The UTRGV faculty roster contains a duplicate email.")
    configured_identity_names = [
        name.casefold()
        for entry in FACULTY_ROSTER
        for name in (entry.display_name, *entry.aliases)
    ]
    if len(set(configured_identity_names)) != len(configured_identity_names):
        raise ValueError("The UTRGV faculty roster contains an ambiguous alias.")

    course_ids = {
        row["code"]: row["id"]
        for row in db.execute(
            "SELECT id,code FROM courses WHERE program_id=?", (program_id,)
        )
    }
    configured_course_codes = {
        code for entry in FACULTY_ROSTER for code in entry.course_codes
    }
    missing_courses = sorted(configured_course_codes - course_ids.keys())
    if missing_courses:
        raise ValueError(
            "The UTRGV faculty roster refers to missing course(s): "
            + ", ".join(missing_courses)
        )

    retained_roster_ids: set[int] = set()
    for entry in FACULTY_ROSTER:
        identity_names = (entry.display_name, *entry.aliases)
        placeholders = ",".join("?" for _ in identity_names)
        candidates = db.execute(
            f"""SELECT id,legacy_name,user_id,status
                  FROM faculty_roster
                 WHERE program_id=? AND legacy_name IN ({placeholders})
                 ORDER BY CASE WHEN legacy_name=? THEN 0 ELSE 1 END,id""",
            (program_id, *identity_names, entry.display_name),
        ).fetchall()

        canonical = next(
            (row for row in candidates if row["legacy_name"] == entry.display_name),
            None,
        )
        if canonical is None and candidates:
            # Prefer the historical row that is already linked to an account so
            # the migration never disconnects an activated faculty member.
            canonical = next(
                (row for row in candidates if row["user_id"] is not None),
                candidates[0],
            )
            db.execute(
                "UPDATE faculty_roster SET legacy_name=? WHERE id=?",
                (entry.display_name, canonical["id"]),
            )
        elif canonical is None:
            roster_id = db.execute(
                """INSERT INTO faculty_roster
                   (program_id,legacy_name,display_name,approved_email)
                   VALUES (?,?,?,?)""",
                (
                    program_id,
                    entry.display_name,
                    entry.display_name,
                    entry.approved_email,
                ),
            ).lastrowid
            canonical = db.execute(
                "SELECT id,legacy_name,user_id,status FROM faculty_roster WHERE id=?",
                (roster_id,),
            ).fetchone()

        canonical_id = canonical["id"]
        canonical_user_id = canonical["user_id"]

        # If a canonical pending row and an activated legacy-alias row both
        # exist, retain the activated identity on the canonical row.
        linked_aliases = [
            row
            for row in candidates
            if row["id"] != canonical_id and row["user_id"] is not None
        ]
        if canonical_user_id is None and len(linked_aliases) == 1:
            linked_alias = linked_aliases[0]
            canonical_user_id = linked_alias["user_id"]
            db.execute(
                "UPDATE faculty_roster SET user_id=?,status='active' WHERE id=?",
                (canonical_user_id, canonical_id),
            )
            db.execute(
                "UPDATE faculty_roster SET user_id=NULL WHERE id=?",
                (linked_alias["id"],),
            )

        # Release an obsolete duplicate's allowlisted address before assigning
        # it to the canonical identity.  This also makes the function resilient
        # to partially completed earlier migrations.
        db.execute(
            """UPDATE faculty_roster SET approved_email=NULL
                 WHERE program_id=? AND approved_email=? AND id<>?""",
            (program_id, entry.approved_email, canonical_id),
        )
        db.execute(
            """UPDATE faculty_roster
                  SET display_name=?,approved_email=?
                WHERE id=?""",
            (entry.display_name, entry.approved_email, canonical_id),
        )

        duplicate_ids = [row["id"] for row in candidates if row["id"] != canonical_id]
        for duplicate_id in duplicate_ids:
            duplicate = db.execute(
                "SELECT user_id,status FROM faculty_roster WHERE id=?",
                (duplicate_id,),
            ).fetchone()
            db.execute(
                "DELETE FROM faculty_roster_courses WHERE faculty_roster_id=?",
                (duplicate_id,),
            )
            db.execute(
                "DELETE FROM faculty_roster_course_campuses WHERE faculty_roster_id=?",
                (duplicate_id,),
            )
            if duplicate["user_id"] is None and duplicate["status"] == "pending":
                db.execute("DELETE FROM faculty_roster WHERE id=?", (duplicate_id,))
            else:
                db.execute(
                    """UPDATE faculty_roster
                          SET status='inactive',approved_email=NULL
                        WHERE id=?""",
                    (duplicate_id,),
                )
                if duplicate["user_id"] is not None:
                    db.execute(
                        """DELETE FROM course_campus_assignments
                            WHERE user_id=? AND course_id IN
                                  (SELECT id FROM courses WHERE program_id=?)""",
                        (duplicate["user_id"], program_id),
                    )
                    db.execute(
                        """DELETE FROM course_assignments
                            WHERE user_id=? AND course_id IN
                                  (SELECT id FROM courses WHERE program_id=?)""",
                        (duplicate["user_id"], program_id),
                    )

        db.execute(
            "DELETE FROM faculty_roster_courses WHERE faculty_roster_id=?",
            (canonical_id,),
        )
        db.execute(
            "DELETE FROM faculty_roster_course_campuses WHERE faculty_roster_id=?",
            (canonical_id,),
        )
        db.executemany(
            """INSERT INTO faculty_roster_courses(faculty_roster_id,course_id)
               VALUES (?,?)""",
            [(canonical_id, course_ids[code]) for code in entry.course_codes],
        )
        db.executemany(
            """INSERT INTO faculty_roster_course_campuses
               (faculty_roster_id,course_id,campus) VALUES (?,?,?)""",
            [
                (canonical_id, course_ids[code], campus)
                for code in entry.course_codes
                for campus in CAMPUS_NAMES
            ],
        )

        # Activation copies both the compatibility course list and exact pairs.
        # Keep an already activated account in sync when the approved mapping is
        # repaired on an existing installation.
        canonical_user_id = db.execute(
            "SELECT user_id FROM faculty_roster WHERE id=?", (canonical_id,)
        ).fetchone()["user_id"]
        if canonical_user_id is not None:
            db.execute(
                """DELETE FROM course_campus_assignments
                    WHERE user_id=? AND course_id IN
                          (SELECT id FROM courses WHERE program_id=?)""",
                (canonical_user_id, program_id),
            )
            db.execute(
                """DELETE FROM course_assignments
                    WHERE user_id=? AND course_id IN
                          (SELECT id FROM courses WHERE program_id=?)""",
                (canonical_user_id, program_id),
            )
            db.executemany(
                "INSERT INTO course_assignments(course_id,user_id) VALUES (?,?)",
                [(course_ids[code], canonical_user_id) for code in entry.course_codes],
            )
            db.executemany(
                """INSERT INTO course_campus_assignments
                   (course_id,user_id,campus) VALUES (?,?,?)""",
                [
                    (course_ids[code], canonical_user_id, campus)
                    for code in entry.course_codes
                    for campus in CAMPUS_NAMES
                ],
            )
        retained_roster_ids.add(canonical_id)

    # Only known identities from the superseded built-in roster are retired.
    # An owner may add other invitations, and an idempotent seed repair must
    # never delete or disable those owner-approved rows.
    existing_rows = db.execute(
        f"""SELECT id,user_id,status FROM faculty_roster
             WHERE program_id=?
               AND legacy_name IN ({','.join('?' for _ in OBSOLETE_SEEDED_FACULTY)})""",
        (program_id, *OBSOLETE_SEEDED_FACULTY),
    ).fetchall()
    for row in existing_rows:
        if row["id"] in retained_roster_ids:
            continue
        db.execute(
            "DELETE FROM faculty_roster_courses WHERE faculty_roster_id=?",
            (row["id"],),
        )
        db.execute(
            "DELETE FROM faculty_roster_course_campuses WHERE faculty_roster_id=?",
            (row["id"],),
        )
        if row["user_id"] is None and row["status"] == "pending":
            db.execute("DELETE FROM faculty_roster WHERE id=?", (row["id"],))
        else:
            db.execute(
                """UPDATE faculty_roster
                      SET status='inactive',approved_email=NULL
                    WHERE id=?""",
                (row["id"],),
            )
            if row["user_id"] is not None:
                db.execute(
                    """DELETE FROM course_campus_assignments
                        WHERE user_id=? AND course_id IN
                              (SELECT id FROM courses WHERE program_id=?)""",
                    (row["user_id"], program_id),
                )
                db.execute(
                    """DELETE FROM course_assignments
                        WHERE user_id=? AND course_id IN
                              (SELECT id FROM courses WHERE program_id=?)""",
                    (row["user_id"], program_id),
                )


def seed_utrgv_mece(db, organization_id: int, program_id: int) -> None:
    """Install or repair the exact UTRGV legacy catalog without creating accounts."""
    db.execute(
        "UPDATE organizations SET name=?,primary_color=?,accent_color=? WHERE id=?",
        (ORGANIZATION_NAME, PRIMARY_COLOR, ACCENT_COLOR, organization_id),
    )
    db.execute(
        "UPDATE programs SET code=?,name=?,commission='EAC',degree_level='Bachelor' WHERE id=?",
        (PROGRAM_CODE, PROGRAM_NAME, program_id),
    )

    for code, name in COURSES:
        db.execute(
            """INSERT INTO courses(program_id,code,name) VALUES (?,?,?)
               ON CONFLICT(program_id,code) DO UPDATE SET name=excluded.name,is_active=1""",
            (program_id, code, name),
        )
    for term in TERMS:
        db.execute(
            """INSERT INTO academic_terms(program_id,name,sort_order) VALUES (?,?,?)
               ON CONFLICT(program_id,name) DO UPDATE SET sort_order=excluded.sort_order,is_active=1""",
            (program_id, term, _term_order(term)),
        )

    # Replace the generic starter definitions with the customer-approved legacy model.
    existing = {row["code"]: row["id"] for row in db.execute("SELECT id,code FROM outcomes WHERE program_id=?", (program_id,))}
    for order, (code, description) in enumerate(OUTCOMES, 1):
        outcome_id = existing.get(code) or existing.get(code.removeprefix("SLO"))
        if outcome_id:
            db.execute(
                "UPDATE outcomes SET code=?,description=?,display_order=?,is_active=1 WHERE id=?",
                (code, description, order, outcome_id),
            )
        else:
            outcome_id = db.execute(
                "INSERT INTO outcomes(program_id,code,description,display_order) VALUES (?,?,?,?)",
                (program_id, code, description, order),
            ).lastrowid
        existing_indicators = {
            row["code"]: row["id"]
            for row in db.execute("SELECT id,code FROM performance_indicators WHERE outcome_id=?", (outcome_id,))
        }
        for pi_order, (pi_code, pi_description) in enumerate(INDICATORS[code], 1):
            if pi_code in existing_indicators:
                db.execute(
                    "UPDATE performance_indicators SET description=?,display_order=?,is_active=1 WHERE id=?",
                    (pi_description, pi_order, existing_indicators[pi_code]),
                )
            else:
                db.execute(
                    "INSERT INTO performance_indicators(outcome_id,code,description,display_order) VALUES (?,?,?,?)",
                    (outcome_id, pi_code, pi_description, pi_order),
                )

    outcome_ids = {row["code"]: row["id"] for row in db.execute("SELECT id,code FROM outcomes WHERE program_id=?", (program_id,))}
    for outcome_code, pi_code, description in HISTORICAL_INDICATORS:
        db.execute(
            """INSERT INTO performance_indicators(outcome_id,code,description,display_order,is_active)
               VALUES (?,?,?,?,0) ON CONFLICT(outcome_id,code) DO UPDATE SET description=excluded.description""",
            (outcome_ids[outcome_code], pi_code, description, 90),
        )

    seed_utrgv_faculty_roster(db, program_id)
