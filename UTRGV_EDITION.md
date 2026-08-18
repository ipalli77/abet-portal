# UTRGV Mechanical Engineering two-campus edition

This edition is a separate customer profile over the commercial AccreditationOS core. It provides one shared ABET evidence workspace for the UTRGV Mechanical Engineering program at the **Edinburg** and **Brownsville** campuses. It does not overwrite `main.py`, `ABET_Data_Rev1.py`, `edinburg_abet_data.db`, `graduate_survey.db`, or the generic platform database.

## Preserved customer configuration

- UTRGV Department of Mechanical Engineering branding and green/orange palette
- All 16 course definitions, including MECE 3336 even though it has no current source rows
- The owner account `isaac.palli@utrgv.edu`, with unrestricted administrative control across the program
- The approved 13-person faculty roster, 13 institutional email addresses, and 15 faculty-to-course assignments
- Invitation-only faculty access: the owner allowlists the exact UTRGV email and course–campus combinations before an administrator can activate an account
- One owner-managed Faculty View support login, with no preset credentials, for verifying normal faculty navigation and visibility within one active course and Edinburg, Brownsville, or both
- Fall 2020 through Fall 2026 terms from the original selector
- SLO1–SLO7 descriptions, the current PI catalog, six Bloom levels, and the EPAN attainment model
- Preserved SLO5 PI meanings as separate inactive aliases, preventing source evidence from being silently relabeled
- A required Edinburg or Brownsville campus designation on every new faculty-entered assessment
- Faculty-scoped data entry with an authorized course–campus combination, assessment tool, alignment rationale, Bloom level, direct EPAN percentages, observations, and closing-the-loop notes
- No sample-size entry in the UTRGV workflow; Expert, Practitioner, Apprentice, and Novice are all required and must total exactly 100%
- Draft, submit, return, and coordinator approval workflow
- Administrator bulk approval by selected records, selected courses, or every eligible record matching the current Assessment filters
- Faculty reopening of their own submitted evidence, with automatic return to draft and required resubmission
- Administrator-managed password recovery through a verified temporary password and forced password replacement
- Selectable one-or-many-course analysis with campus, course, term, outcome, PI, method, and workflow-state filters
- Edinburg–Brownsville comparison organized by academic term, course, student outcome, or performance indicator; campus means, targets, target-adjusted gaps, paired-dot charts, exact-value tables, accessible alternatives, and clear insufficient-data states
- Course/term charts, PI + Bloom comparisons, Bloom boxplots, Kruskal–Wallis and Cliff's delta, chronological trends, course/outcome heatmaps, accessible data tables, and filtered export
- Approved-only official results and a prominently labeled workflow preview, plus evidence attachments, improvement actions, audit history, and print/PDF reporting

Faculty names, institutional emails, and course scopes are initially installed as approved pending invitations, not as insecure accounts. An owner controls the allowlist; an owner or administrator assigns a temporary password and activates an approved roster entry. The user is forced to replace that password at first sign-in. No password from the original Python files is reused.

The **Users and scoped access** page shows both active accounts and every approved faculty invitation, including pending faculty, their exact institutional email, assigned course–campus combinations, and activation status. After activation, a faculty member's dashboard, assessment list and forms, analysis, report, CSV export, evidence files, and course-linked improvement actions are restricted to those exact combinations. For example, access to MECE 1101 at Edinburg does not reveal or permit MECE 1101 evidence from Brownsville. The owner remains unrestricted across the complete program.

### Faculty View support login

The owner can create one separately marked **Faculty View support login** from **Configure → Users & access**. Its display name is permanently fixed as **Faculty View Support** so assessment and audit provenance cannot be renamed. The owner chooses its institutional email, optional sign-in name, and temporary password; the product contains no default or hardcoded support credentials. The owner can later update the email or sign-in name, issue a new temporary password, disable the login, or reactivate it with a new temporary password.

After signing in, the support user selects exactly one active course and Edinburg, Brownsville, or both. The selected scope applies to every simultaneous browser session using this one account. A prominent Faculty View banner appears on every page, states the current course–campus scope, provides a **Switch faculty view** link, and warns that this is not a sandbox.

This account has the standard Faculty role. It reproduces faculty navigation and data visibility for the selected scope; it does not impersonate a named faculty member and does not inherit another faculty member's record ownership. Existing faculty-owned records may therefore be read-only. Assessments created or edited through the support login are real program records, retained in the database and audit history, and attributed to the support account.

### Approved faculty and course access

| Faculty | Approved email | Courses | Initial campus access |
| --- | --- | --- | --- |
| Yingchen Yang | yingchen.yang@utrgv.edu | MECE 1101 | Edinburg and Brownsville |
| Lawrence Cano | lawrence.cano@utrgv.edu | MECE 1221 | Edinburg and Brownsville |
| Misael Martinez | misael.e.martinez01@utrgv.edu | MECE 2140 | Edinburg and Brownsville |
| Eleazar Marquez | eleazar.marquez01@utrgv.edu | MECE 2302, MECE 4362 | Edinburg and Brownsville for each course |
| Robert Jones | robert.jones@utrgv.edu | MECE 2340 | Edinburg and Brownsville |
| Jose Sanchez | jose.j.sanchez01@utrgv.edu | MECE 3170, MECE 3336 | Edinburg and Brownsville for each course |
| Nadim Zgheib | nadim.zgheib@utrgv.edu | MECE 3315 | Edinburg and Brownsville |
| Constantine Tarawneh | constantine.tarawneh@utrgv.edu | MECE 3360 | Edinburg and Brownsville |
| Robert Freeman | robert.freeman@utrgv.edu | MECE 3380 | Edinburg and Brownsville |
| Dumitru Caruntu | dumitru.caruntu@utrgv.edu | MECE 3450 | Edinburg and Brownsville |
| Javier Ortega | javier.ortega@utrgv.edu | MECE 4350 | Edinburg and Brownsville |
| Noe Vargas | noe.vargas@utrgv.edu | MECE 4361 | Edinburg and Brownsville |
| Mataz Alcoutlabi | mataz.alcoutlabi@utrgv.edu | PHIL 2393 | Edinburg and Brownsville |

MECE 3320 has no faculty assignment in the supplied mapping. The owner remains unrestricted and can manage that course and every other program resource.

## Roles and day-to-day workflow

### Owner or administrator

1. Complete first-run setup and retain the owner credentials securely.
2. Open **Configure → Users & access → UTRGV faculty roster**. The supplied faculty are already listed with their approved institutional emails and course assignments.
3. Create a temporary password and activate each approved faculty account as needed. The email cannot be replaced during activation, and the faculty member must change the temporary password at first sign-in.
4. To authorize a future faculty member, use **Add approved faculty**. For each course, select Edinburg, Brownsville, or both. Selecting neither campus leaves that course unassigned. Only the owner may allowlist or change a faculty email and exact course–campus scope; adding an invitation does not create an account. An owner or administrator can activate it afterward.
5. If a faculty member forgets a password, verify the person's identity through a UTRGV-approved channel, then open **Configure → Users & access** (or the **UTRGV faculty roster**) and choose **Set temporary password**. Share it securely. The account is required to replace it at the next sign-in.
6. When support staff need to verify faculty-visible screens, configure the dedicated **Faculty View support login** on **Users & access**. Do not share an owner account. The support user selects one course and one or both campuses after signing in; changing that selection affects all of its active sessions. Treat any data entry through this login as a real, audited program change.
7. Review all Edinburg and Brownsville records in **Assessment**. Return submitted evidence for correction or approve it for official analysis and reporting.
8. To approve a batch, use **Approve multiple records** on the Assessment page. Choose individual record checkboxes, one or more course checkboxes, or **All matching records**. The active status, campus, term, course, and outcome filters define the batch. Draft and submitted records are eligible; approved and returned records are left unchanged.
9. Before a batch is changed, the server rechecks every selected record, including all required fields and the exact 100% EPAN total. If any selected record is incomplete or changed concurrently, the entire batch is stopped so approval cannot be partial. Each approval records the administrator, time, selection method, and batch identifier in the audit history.
10. Administrators may open any assessment, change its campus or other data, and save it. The record identifies that it was changed by an administrator, and the change is retained in the audit history.
11. Use **Analysis** to select one or both campuses and the courses, terms, outcomes, performance indicators, and methods needed for the ABET review.
12. When both campuses are selected, organize the comparison by term, course, outcome, or performance indicator. Use **Print analysis** or **Report** for visit-ready output.

The owner, administrator, and coordinator roles can view program evidence from both campuses. The official Analysis and Report views use approved evidence; the explicitly labeled preview may include draft, submitted, and returned records.

### Faculty

1. Sign in with the activated account and replace the temporary password when prompted.
2. The Overview, Assessment, Analysis, Improvement, Report, exports, and evidence downloads automatically show only information linked to the faculty member's assigned course–campus combinations.
3. Choose **Assessment → New assessment**.
4. Select **Edinburg** or **Brownsville** according to where the assessed student group completed the course. Campus is required, and the course list immediately narrows to courses approved for that campus. Selecting a course likewise narrows the campus choices. Unauthorized combinations cannot be saved.
5. Select an available course, term, outcome, performance indicator, method, Bloom level, target, and interpretation. Enter Expert, Practitioner, Apprentice, and Novice directly as percentages. The page shows the running total and blocks saving until it equals exactly 100%.
6. Complete every assessment field, save the record as a draft, revise it as needed, attach supporting evidence, and submit it for review. The server rechecks completeness and the EPAN total before submission or approval.
7. Faculty may edit their own draft or returned records in assigned courses. They may also reopen their own submitted record after signing in again; the page clearly warns that saving returns it to draft, clears the earlier submission, and requires another submission. Approved records remain protected, while an owner or administrator can make an audited correction when necessary.

If a faculty member forgets a password, use **Forgot password?** on the sign-in page for instructions and contact the program owner or administrator through a UTRGV-approved channel. The public recovery page never asks for an account name and never reveals whether an account exists. Because this edition does not send recovery email, a locked-out owner must contact the deployment/system administrator or another provisioned owner; maintain a second owner or a documented institutional break-glass procedure before production use.

Campus describes the assessed student group, not the faculty member's office, the course owner, or a guess based on the course number.

## Current Edinburg data and campus assignment

The current source is `edinburg_abet_data.db`. Its `abet_entries` table stores course, course name, SLO, PI, assessment tool, explanation, semester, Bloom level, EPAN percentages, and observations. Although the table itself has no campus column, UTRGV has confirmed that every row currently belongs to **Edinburg**. The application therefore assigns this configured source explicitly to Edinburg during import.

There is no Brownsville database and none is required. Faculty with Brownsville permission for a course create its Brownsville assessments directly in the software by selecting that approved course–campus combination on the assessment form.

When `edinburg_abet_data.db` is kept in the project folder, the UTRGV entry point detects it automatically. If it is stored elsewhere, set:

```bash
export UTRGV_EDINBURG_ABET_DB="/absolute/path/to/edinburg_abet_data.db"
```

The source-data screen is intentionally absent from the primary menu. An owner, administrator, or coordinator can open **Configure → Manage Edinburg source data** when the current source rows need to be loaded. The source is opened with SQLite `mode=ro` and `query_only=ON`; importing never writes to `edinburg_abet_data.db`.

The **Import unseen source rows** action:

- is idempotent and skips source IDs that have already been imported;
- imports source rows as drafts for review before they enter official results;
- assigns every imported assessment to Edinburg;
- retains the fractional Expert, Practitioner, Apprentice, and Novice percentages;
- stores no sample size because the UTRGV evidence model is percentage based, and labels the source collector as unknown because that identity was not stored;
- preserves PI descriptions and creates an explicit unmapped indicator for the one blank-PI record;
- allows an administrator to correct the campus or other record data afterward, with an administrator-change note and audit entry;
- never writes to the source database.

If rows were imported into the platform before campus support, an administrator can use the campus-assignment control on the source-data screen to assign the unresolved batch to Edinburg. An administrator can also open an individual record in **Assessment** and change its campus when a correction is necessary.

The current Edinburg source contains 318 submitted records and one unsent draft. The separate graduate survey database contains no responses.

Imported and faculty-entered rows retain their exact Expert, Practitioner, Apprentice, and Novice percentages for all calculations. Analysis treats every assessment measure equally because the source database did not store student denominators; internal compatibility values are never used as a statistical weight. UTRGV CSV import and export use the four percentage columns and do not use a sample-size column. The default Analysis view remains approved-only, while **Preview all workflow states** exposes imported drafts without presenting them as official accreditation findings.

Campus comparisons are descriptive comparisons of assessment-measure attainment, not causal or student-level significance tests. Different courses, terms, instruments, populations, sample sizes, and evidence coverage can affect an Edinburg–Brownsville difference. Missing campus/group combinations are shown as no evidence and are never converted to zero.

## Local evaluation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
flask --app utrgv_wsgi:app run --port 5001
```

The project entry point automatically recognizes `./edinburg_abet_data.db` as the Edinburg source. Open `http://127.0.0.1:5001/setup`, create the owner account, sign in, and visit **Configure → Users & access → UTRGV faculty roster** to activate faculty. Use **Configure → Manage Edinburg source data** to import current Edinburg rows. Keep the terminal open while using the application; press `Control+C` to stop it.

For later runs:

```bash
cd /absolute/path/to/ABET_New
source .venv/bin/activate
flask --app utrgv_wsgi:app run --port 5001
```

The default local application database is `instance/utrgv_mece.db`. Back up this database and the configured upload folder together.

## Dedicated container

```bash
docker build -f Dockerfile.utrgv -t utrgv-me-accreditation .
docker run --rm -p 8000:8000 \
  -e ABET_SECRET_KEY="<random deployment secret>" \
  -e ABET_SETUP_TOKEN="<separate one-time setup token>" \
  -v utrgv-me-data:/data \
  -e UTRGV_EDINBURG_ABET_DB=/legacy/edinburg_abet_data.db \
  -v /absolute/path/to/edinburg_abet_data.db:/legacy/edinburg_abet_data.db:ro \
  utrgv-me-accreditation
```

No Brownsville database mount is needed. Faculty enter Brownsville records through their assigned-course assessment forms. Mount the Edinburg source read-only, retain its SHA-256 fingerprint, and back up the writable platform database and upload directory together.

## Customer acceptance boundary

The edition deliberately does not copy missing or unsafe behavior from the earlier prototype. The three intervention PDFs and turbine image referenced by the prototype are absent from the supplied folder, the old checklist never persisted its state, and the supporting-material page points to a personal SharePoint URL. Those assets/workflows require UTRGV-approved content and storage destinations before customer acceptance. The new evidence library and improvement-action workflow replace the personal SharePoint dependency.

Before production purchase, UTRGV should provide verified faculty addresses, approved brand/logo assets, retention rules, an institutional storage destination, and an Entra ID/OIDC or SAML integration decision. Accessibility certification, penetration testing, FERPA review, backup restoration testing, and contractual support terms remain release gates.
