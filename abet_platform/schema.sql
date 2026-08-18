PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_versions (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS organizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    timezone TEXT NOT NULL DEFAULT 'America/Chicago',
    primary_color TEXT NOT NULL DEFAULT '#12355b',
    accent_color TEXT NOT NULL DEFAULT '#ef8354',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    username TEXT UNIQUE COLLATE NOCASE,
    full_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    must_change_password INTEGER NOT NULL DEFAULT 0 CHECK (must_change_password IN (0, 1)),
    last_login_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL COLLATE NOCASE,
    ip_address TEXT NOT NULL,
    success INTEGER NOT NULL DEFAULT 0 CHECK (success IN (0, 1)),
    attempted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS memberships (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'coordinator', 'faculty', 'reviewer')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, organization_id)
);

CREATE TABLE IF NOT EXISTS programs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    commission TEXT NOT NULL DEFAULT 'EAC',
    degree_level TEXT NOT NULL DEFAULT 'Bachelor',
    mission TEXT NOT NULL DEFAULT '',
    cycle_start TEXT,
    cycle_end TEXT,
    default_target REAL NOT NULL DEFAULT 70 CHECK (default_target BETWEEN 0 AND 100),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (organization_id, code)
);

CREATE TABLE IF NOT EXISTS program_members (
    program_id INTEGER NOT NULL REFERENCES programs(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    access_level TEXT NOT NULL DEFAULT 'editor' CHECK (access_level IN ('viewer', 'editor', 'manager')),
    PRIMARY KEY (program_id, user_id)
);

CREATE TABLE IF NOT EXISTS academic_terms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id INTEGER NOT NULL REFERENCES programs(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    starts_on TEXT,
    ends_on TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    UNIQUE (program_id, name)
);

CREATE TABLE IF NOT EXISTS courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id INTEGER NOT NULL REFERENCES programs(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    UNIQUE (program_id, code)
);

CREATE TABLE IF NOT EXISTS course_assignments (
    course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    PRIMARY KEY (course_id, user_id)
);

CREATE TABLE IF NOT EXISTS faculty_roster (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id INTEGER NOT NULL REFERENCES programs(id) ON DELETE CASCADE,
    legacy_name TEXT NOT NULL,
    display_name TEXT NOT NULL,
    approved_email TEXT COLLATE NOCASE,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'active', 'inactive')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (program_id, legacy_name)
);

CREATE TABLE IF NOT EXISTS faculty_roster_courses (
    faculty_roster_id INTEGER NOT NULL REFERENCES faculty_roster(id) ON DELETE CASCADE,
    course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    PRIMARY KEY (faculty_roster_id, course_id)
);

-- UTRGV invitations are authorized at the exact course/campus intersection.
-- The course-only table above remains for generic-edition compatibility and
-- for displaying the distinct course catalog attached to an invitation.
CREATE TABLE IF NOT EXISTS faculty_roster_course_campuses (
    faculty_roster_id INTEGER NOT NULL REFERENCES faculty_roster(id) ON DELETE CASCADE,
    course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    campus TEXT NOT NULL CHECK (campus IN ('Edinburg', 'Brownsville')),
    PRIMARY KEY (faculty_roster_id, course_id, campus)
);

-- Active UTRGV faculty accounts receive a durable copy of the invitation's
-- exact scope.  ``course_assignments`` remains authoritative for the generic
-- edition; this table is authoritative for UTRGV assessment evidence.
CREATE TABLE IF NOT EXISTS course_campus_assignments (
    course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    campus TEXT NOT NULL CHECK (campus IN ('Edinburg', 'Brownsville')),
    PRIMARY KEY (course_id, user_id, campus)
);

-- One separately authenticated faculty-view support account may be explicitly
-- marked for each program.  Its membership remains Faculty; this marker only
-- exempts that exact user/program pair from the invitation-roster login check.
CREATE TABLE IF NOT EXISTS program_support_accounts (
    program_id INTEGER PRIMARY KEY REFERENCES programs(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    configured_by INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id INTEGER NOT NULL REFERENCES programs(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    description TEXT NOT NULL,
    display_order INTEGER NOT NULL DEFAULT 0,
    target REAL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    UNIQUE (program_id, code)
);

CREATE TABLE IF NOT EXISTS performance_indicators (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    outcome_id INTEGER NOT NULL REFERENCES outcomes(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    description TEXT NOT NULL,
    display_order INTEGER NOT NULL DEFAULT 0,
    target REAL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    UNIQUE (outcome_id, code)
);

CREATE TABLE IF NOT EXISTS rubrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id INTEGER NOT NULL REFERENCES programs(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1)),
    UNIQUE (program_id, name)
);

CREATE TABLE IF NOT EXISTS rubric_levels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rubric_id INTEGER NOT NULL REFERENCES rubrics(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    score REAL NOT NULL,
    is_attained INTEGER NOT NULL DEFAULT 0 CHECK (is_attained IN (0, 1)),
    display_order INTEGER NOT NULL DEFAULT 0,
    UNIQUE (rubric_id, label)
);

CREATE TABLE IF NOT EXISTS assessment_records (
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
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'submitted', 'approved', 'returned')),
    submitted_at TEXT,
    approved_at TEXT,
    record_version INTEGER NOT NULL DEFAULT 1 CHECK (record_version > 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS assessment_results (
    assessment_id INTEGER NOT NULL REFERENCES assessment_records(id) ON DELETE CASCADE,
    rubric_level_id INTEGER NOT NULL REFERENCES rubric_levels(id),
    student_count INTEGER NOT NULL DEFAULT 0 CHECK (student_count >= 0),
    level_percent REAL CHECK (level_percent IS NULL OR level_percent BETWEEN 0 AND 100),
    PRIMARY KEY (assessment_id, rubric_level_id)
);

CREATE TABLE IF NOT EXISTS evidence_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    program_id INTEGER NOT NULL REFERENCES programs(id) ON DELETE CASCADE,
    assessment_id INTEGER REFERENCES assessment_records(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    evidence_type TEXT NOT NULL DEFAULT 'other',
    source_url TEXT,
    storage_key TEXT,
    original_filename TEXT,
    mime_type TEXT,
    uploaded_by INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (source_url IS NOT NULL OR storage_key IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS improvement_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id INTEGER NOT NULL REFERENCES programs(id) ON DELETE CASCADE,
    outcome_id INTEGER REFERENCES outcomes(id) ON DELETE SET NULL,
    assessment_id INTEGER REFERENCES assessment_records(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    owner_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    due_on TEXT,
    status TEXT NOT NULL DEFAULT 'planned' CHECK (status IN ('planned', 'in_progress', 'completed', 'verified', 'cancelled')),
    impact_summary TEXT NOT NULL DEFAULT '',
    created_by INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    details_json TEXT NOT NULL DEFAULT '{}',
    ip_address TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS assessment_revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id INTEGER NOT NULL REFERENCES programs(id) ON DELETE CASCADE,
    assessment_id INTEGER NOT NULL REFERENCES assessment_records(id) ON DELETE CASCADE,
    changed_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    changed_by_name TEXT NOT NULL,
    change_note TEXT NOT NULL,
    before_json TEXT NOT NULL,
    after_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS legacy_import_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id INTEGER NOT NULL REFERENCES programs(id) ON DELETE CASCADE,
    source_fingerprint TEXT NOT NULL,
    source_record_id INTEGER NOT NULL,
    assessment_id INTEGER NOT NULL REFERENCES assessment_records(id) ON DELETE CASCADE,
    expert_percent REAL NOT NULL,
    practitioner_percent REAL NOT NULL,
    apprentice_percent REAL NOT NULL,
    novice_percent REAL NOT NULL,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (program_id, source_fingerprint, source_record_id)
);

CREATE INDEX IF NOT EXISTS idx_programs_org ON programs(organization_id);
CREATE INDEX IF NOT EXISTS idx_assessments_program ON assessment_records(program_id, status, term_id);
CREATE INDEX IF NOT EXISTS idx_assessments_dimensions ON assessment_records(outcome_id, indicator_id, course_id);
CREATE INDEX IF NOT EXISTS idx_evidence_program ON evidence_items(program_id, assessment_id);
CREATE INDEX IF NOT EXISTS idx_actions_program ON improvement_actions(program_id, status);
CREATE INDEX IF NOT EXISTS idx_audit_org ON audit_events(organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_assessment_revisions
    ON assessment_revisions(program_id, assessment_id, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_login_attempts ON login_attempts(email, ip_address, attempted_at DESC);
CREATE INDEX IF NOT EXISTS idx_legacy_import_source ON legacy_import_items(program_id, source_fingerprint);
CREATE UNIQUE INDEX IF NOT EXISTS idx_legacy_import_assessment ON legacy_import_items(assessment_id);
CREATE INDEX IF NOT EXISTS idx_faculty_roster_program ON faculty_roster(program_id, status);
CREATE INDEX IF NOT EXISTS idx_roster_course_campuses
    ON faculty_roster_course_campuses(faculty_roster_id, course_id, campus);
CREATE INDEX IF NOT EXISTS idx_user_course_campuses
    ON course_campus_assignments(user_id, course_id, campus);
CREATE UNIQUE INDEX IF NOT EXISTS idx_program_support_user
    ON program_support_accounts(user_id);

INSERT OR IGNORE INTO schema_versions(version) VALUES (1);
