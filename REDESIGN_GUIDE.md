# UTRGV Mechanical Engineering — evidence-first portal redesign

Prepared 16 September 2026. This is a local, tested redesign, not a deployment to Render.

## What changed

- **Overview:** a neutral assessment-summary title, approved-evidence scope, outcome cards, workflow counts, and links to the underlying records.
- **Evaluator view:** a read-only presentation organized around student outcomes, faculty response, campus evidence, and source verification. This view does not confer additional permissions.
- **Analysis:** six focused views—Summary, Courses & trends, Performance indicators, Campus comparison, Bloom & statistics, and Source records. Filters persist between tabs and exports. Source records are searchable and paginated, 20 at a time.
- **Continuous improvement:** four documented case stories, each separating the finding, implemented action, reassessment, faculty decision, and next review. The full submitted narrative remains available in a disclosure section.
- **Evidence:** a protected library linking the submitted chapter, detailed Criterion 4 documents, proposed interventions, implemented rubrics, and authorized assessment attachments.
- **Reports:** an approved-only report with scope, findings, campus figures, improvement cases, sources, and an optional full narrative appendix. Expand the appendix before printing if it should be included.
- **Figures:** full-width readable presentation, enlarge links, and 300-dpi PNG, SVG, and PDF downloads. Exports carry evidence scope and approval-state captions. Existing shared PI blocks, unconnected observations, campus-specific fits, colorful symbols, and 110% upper plotting limits are retained.
- **Performance:** only the active view's charts are rendered. A bounded, five-minute, process-local cache reuses results only after fresh authorization and record reads. Changed data or permissions invalidate reuse. Authenticated responses are marked `no-store`.
- **Wording:** short descriptive headings replace sentence-style titles. The aggregate under-target headline and its explanatory paragraph have been removed from the evaluator page. Detailed results and qualifications remain available in the outcome cards, analyses, and reports.

## Where to find existing controls

- Faculty enter and edit records through **Assessment**. Their course/campus assignments continue to govern all records, analysis, reports, exports, and attachments.
- Administrators continue to edit, move campus assignments, approve selected records, and review revision notes through **Assessment**.
- **Configure → Users & access** retains approved-email invitations, course/campus access, account recovery, and the faculty-view support login.
- Selecting **Evaluator view** while signed in as owner is a presentation mode for your existing authorized data, not a separate public or anonymous login. It does not change your administrator rights. Existing reviewer accounts remain limited by their existing assignments.
- Protected program-wide historical case studies and source documents remain manager-only to avoid exposing other courses to faculty or scoped reviewers.

## How to interpret the new presentation

1. Approved live records and the historical submitted narrative are different evidence sets. Each historical case is explicitly labeled and does not change when analysis filters change.
2. “Verified course-level improvement” describes the documented case in the submitted chapter, not a new automated accreditation verdict. Preliminary, mixed, and awaiting-reassessment cases remain visibly separate.
3. Attainment summaries weight assessment measures equally. Percentage-only records are not converted into student sample sizes. Outcome means do not replace individual PI checks.
4. Campus comparisons first look for the same course, term, outcome, PI, method, Bloom level, rubric, and assessment name. Matching names still require faculty confirmation of comparable instruments and grading. Raw campus summaries are separately labeled as unmatched descriptive context.
5. No student-level pathway or graduation success is inferred. Observed evidence is not relabeled as modeled evidence, and no new projection probabilities are invented.
6. A 70% target in the submitted case figures is the program's documented threshold, not an ABET-prescribed percentage. Live figures use configured record targets.

## Safe update of the existing Render deployment

Use the **UTRGV-portal-redesign-code-only.zip** package, not the entire development workspace. The package deliberately excludes databases, uploaded student work, environment files, Render configuration, old standalone entry points, and the auto-authenticated local preview helper.

1. **Back up before deployment.** Take a consistent SQLite backup of the current live database using SQLite's backup API (not a raw copy of an active database with possible WAL files). Preserve the uploads folder separately, and download copies off the server. Confirm the backup opens and record counts are plausible.
2. **Record the existing settings.** Keep the exact current `ABET_DATABASE`, `ABET_UPLOAD_FOLDER`, persistent-disk mount, secret/setup tokens, and faculty accounts. Do not point the service at a local database from this computer.
3. **Review the code diff.** Unzip into a separate folder. Apply the `abet_platform/` files to the existing deployment repository. Compare any newer production changes before replacing overlapping files. The supplied `utrgv_wsgi.py` and `requirements.txt` are unchanged reference copies from the reviewed version; do not overwrite newer versions blindly. Do not copy or commit `instance/`, any `.db` / `-wal` / `-shm` files, `.env`, or local uploads.
4. **Confirm the entry point.** The UTRGV platform entry point in the reviewed code is `utrgv_wsgi:app`, not the old standalone `main:app`. Confirm which application your existing Render service currently runs before changing its start command. A typical compatible start command is `gunicorn --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120 utrgv_wsgi:app`. Retain existing production and persistent-storage settings; do not provision a new blank database.
5. **Deploy code only after review.** Commit the code changes and use the existing service's normal deployment process. This redesign introduces no database schema changes. Its database initialization and migration code are unchanged from the reviewed version; older deployments still require normal staging checks.
6. **Smoke-test with existing accounts.** Check owner access; a faculty account's course/campus isolation; edits and approvals; summary totals against the original selection; all analysis tabs; approved-only reports; artifact downloads; and account recovery. Confirm the live record and account counts are unchanged. Test changes on a staging database first, not on faculty evidence.
7. **Rollback is code-only.** Revert to the prior code release if needed. Do not restore an old database over faculty entries made since the backup.

The seven Criterion 4 source files under `abet_platform/source_documents/` are intentionally not in the public static folder. Downloads require authentication and manager access. Check institutional sharing policy before distributing the package outside UTRGV.

## Local use

The design preview opened with this delivery uses a temporary copy of a historical 17 August 2026 backup. It is read-only and does not represent the current Render data. The preview helper is outside the release package and must never be deployed.

For a normal local installation, install `requirements.txt` in a virtual environment, configure paths to a **separate test database and uploads folder**, then run `python utrgv_wsgi.py` and open `http://127.0.0.1:5001`. Without a test database, the application starts a new workspace; it will not contain your current faculty submissions. Never point a test run at the operational database.

## Verification

- Final regression run: **144 tests run, 143 passed, 1 optional database test skipped**, with no failures. The title regression test confirms that detailed below-target counts are unchanged. JavaScript syntax check passed.
- Automated regression coverage includes login, mandatory percentage entry and totals, administrator audit notes, faculty editing, bulk approval, invitation/account recovery workflows, course/campus isolation, reviewer access, analysis filtering, original statistics and chart behaviors, new read-only views, file formats, and authorization-aware cache invalidation.
- Desktop and 390-pixel responsive presentation were visually checked. The PI PNG and PDF exports were inspected for readable labels and unclipped symbols.
- One optional bundled-database parity test may be skipped because the release intentionally contains no operational database.
- No live Render service, faculty database, account, or student artifact was modified as part of this redesign.

Run the included regression suite from the extracted package with `python -m unittest discover -s tests -v`. Source documents remain controlled snapshots: future revisions to the submitted narrative and case summaries should be reviewed together, not silently substituted.
