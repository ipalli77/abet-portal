# AccreditationOS

AccreditationOS is a configurable, institution-scoped web application for engineering programs managing ABET assessment and continuous-improvement evidence. It is the commercial product foundation in this folder; `main.py` and `ABET_Data_Rev1.py` remain unchanged as the original UTRGV prototype and migration source.

## What the product supports

- Multiple institutions and programs with strict organization and program scoping
- Owner, administrator, coordinator, faculty, and reviewer roles
- Optional faculty-to-course assignments
- Administrator-issued temporary passwords for verified account recovery, with a forced password change at the next sign-in
- UTRGV invitation-only faculty access with owner-approved institutional emails and exact course–campus assignments
- One owner-managed UTRGV Faculty View support login for verifying normal faculty navigation and visibility within one selected course and Edinburg, Brownsville, or both
- UTRGV two-campus evidence collection with a required Edinburg or Brownsville designation on every new assessment
- UTRGV faculty entry of Expert, Practitioner, Apprentice, and Novice directly as percentages, with an exact 100% total enforced in the page and on the server
- Configurable courses, academic terms, student outcomes, performance indicators, targets, and arbitrary scoring rubrics
- Direct and indirect assessment collection with draft, submitted, returned, and approved workflow states
- UTRGV administrator bulk approval for selected records, selected courses, or all eligible records matching the current filters, with atomic validation and batch audit history
- Attainment calculated from whichever rubric levels a program designates as attained
- One-or-many-course analysis filtered by campus, term, outcome, performance indicator, and assessment method
- Course, term, outcome, and PI/Bloom attainment charts; Bloom boxplots with guarded Kruskal–Wallis and Cliff's delta; chronological trend analysis; and course/outcome heatmaps
- Descriptive Edinburg–Brownsville comparison by term, course, student outcome, or performance indicator, with campus-specific targets, exact-value tables, and explicit sparse-data states
- Accessible companion tables, record-level narratives, filtered CSV export, and print-ready analysis views
- Approved-only official results plus an explicitly labeled preview for drafts and source imports
- Evidence files or links attached to individual measures
- Continuous-improvement action ownership, due dates, completion, and impact verification
- CSV bulk import, normalized CSV export, an evidence audit trail, and a print/PDF-ready accreditation narrative
- First-run workspace seeding with the current ABET 1–7 outcome language as an editable starting point

The application intentionally does not encode one department's courses, faculty, credentials, performance indicators, or colors in source code.

## Run locally

Use Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
flask --app wsgi:app run
```

Open `http://127.0.0.1:5000/setup`. The one-time setup creates an institution, first program, owner, default EPAN rubric, and editable ABET outcome starter set.

Run verification with:

```bash
pytest
ruff check abet_platform tests wsgi.py
```

## Production deployment

The supplied container runs Gunicorn as a non-root user. Provide durable storage at `/data`, generate a long random secret, and terminate TLS at a managed load balancer or reverse proxy.

```bash
docker build -t accreditation-os .
export ABET_SETUP_TOKEN_VALUE="$(openssl rand -hex 24)"
echo "One-time setup token: $ABET_SETUP_TOKEN_VALUE"
docker run --rm -p 8000:8000 \
  -e ABET_SECRET_KEY="$(openssl rand -hex 32)" \
  -e ABET_SETUP_TOKEN="$ABET_SETUP_TOKEN_VALUE" \
  -v abet-data:/data \
  accreditation-os
```

Production variables are documented in `.env.example`. `ABET_ENV=production` refuses to start without both `ABET_SECRET_KEY` and the separate `ABET_SETUP_TOKEN`, which prevents an unclaimed deployment from being initialized by an unauthorized visitor. Uploaded evidence is capped at 25 MB by default.

Back up both the SQLite database and upload directory together. SQLite is appropriate for a pilot, a single institution, or a modest single-instance deployment. Before running multiple application replicas or pursuing enterprise procurement, replace the persistence adapter with managed PostgreSQL and object storage; do not place a SQLite database on a multi-writer network filesystem.

## Migrating the original prototype

After first-run setup, point the application at the new database and import the old `abet_entries` table:

```bash
export ABET_DATABASE=/absolute/path/to/new-platform.db
python -m abet_platform.migrate_legacy --source ./abet_data.db --program BSME
```

Legacy EPAN percentages are normalized into a 100-student distribution and imported as drafts so a coordinator can validate them before approval. Courses, terms, and missing indicators are created when needed. Always take a database backup before migration.

For the UTRGV two-campus edition, the current `edinburg_abet_data.db` source is handled through **Configure → Manage Edinburg source data** as described in `UTRGV_EDITION.md`. Its rows are explicitly assigned to Edinburg. No Brownsville database is required; authorized faculty enter Brownsville assessments directly for course–campus combinations approved by the owner.

## Product operation

1. Configure the program profile and review cycle.
2. Add terms and courses, then refine outcomes and measurable indicators.
3. Define one or more rubric models; the `attained` flag controls the numerator used in attainment.
4. Add faculty and assign courses. Reviewer accounts are read-only.
5. Faculty collect evidence and submit it. Faculty may reopen their own submitted record when a correction is needed; saving returns it to draft and requires resubmission. Coordinators return or approve each record.
6. Use Analysis to select one or several courses, compare outcome and PI/Bloom patterns, inspect nonparametric and trend results, and create Improvement actions where findings warrant change.
7. Attach artifacts and use Report to print or save the live continuous-improvement narrative as PDF.

## Security model

Passwords are one-way hashed by Werkzeug. All state-changing forms use per-session CSRF tokens. Session cookies are HTTP-only, secure in production, and expire after eight hours. Tenant IDs are applied to resource queries, program membership is checked before access, uploaded filenames are randomized, login attempts are throttled, and material actions are audited. Browser responses include a restrictive content security policy and clickjacking/MIME protections.

See `SECURITY.md` for deployment responsibilities and the supported disclosure process.

## Analysis methodology

Each assessment measure is one observation. Summary means are deliberately unweighted because imported legacy percentages do not contain a trustworthy student denominator; the application never treats their internal preservation denominator as a sample size. Every measure is evaluated against its own configured target. Kruskal–Wallis, Cliff's delta, and linear trend outputs are labeled exploratory, return a plain-language reason when the selected data are insufficient, and are always accompanied by the underlying descriptive values.

## UTRGV Mechanical Engineering edition

The customer-specific edition has its own entry point, database default, seed profile, current Edinburg source-data workflow, faculty activation workflow, tests, and container. It supports one shared Mechanical Engineering program across the Edinburg and Brownsville campuses. `isaac.palli@utrgv.edu` is the designated owner with unrestricted program control. Faculty accounts are invitation-only: the owner approves the institutional email and exact course–campus scope before activation. For each course, the owner can authorize Edinburg, Brownsville, or both. Campus is required for new evidence, administrators can see and edit both campuses, and faculty can create and revise their own draft, returned, or submitted records only in approved course–campus combinations. The same exact scope limits faculty assessment lists, analysis, reports, exports, evidence, and course-linked improvement work. The owner may also create one separately marked Faculty View support login with no embedded credentials. Its display name is fixed as **Faculty View Support** so saved records and audit events retain unmistakable provenance; the owner controls only its institutional email, optional sign-in name, and password. That login has only the Faculty role and selects one active course plus one or both campuses; its banner remains visible on every page. It reproduces faculty visibility and navigation, not another faculty member's ownership rights. Any data it creates or edits is real, audited, and attributed to the support account. Faculty enter the four EPAN categories directly as percentages; no sample size is requested, and all assessment fields must be complete before a record can be saved or reviewed. Revising a submitted record reopens it as a draft and requires resubmission. Administrators can approve selected records, selected courses, or all eligible records matching the Assessment filters; the operation validates the complete batch before making any change and records it in the audit history. Administrator changes are identified in the record and retained in the audit history.

Run it locally with:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
flask --app utrgv_wsgi:app run --port 5001
```

Then open `http://127.0.0.1:5001/setup`. If `edinburg_abet_data.db` is in this project folder, it is detected automatically as the Edinburg source; Brownsville begins with faculty-entered records. See `UTRGV_EDITION.md` and `.env.utrgv.example` for the complete two-campus setup, faculty workflow, and analysis procedure.

## Commercial launch boundary

This repository now provides a coherent, testable sellable-pilot application. University-wide commercial release still requires work outside source code: legal review of ABET trademark usage, privacy terms and data-processing agreements, accessibility certification, penetration testing, disaster-recovery exercises, support commitments, procurement documentation, and a hosted operations model. Those obligations cannot be truthfully completed by code generation alone.
