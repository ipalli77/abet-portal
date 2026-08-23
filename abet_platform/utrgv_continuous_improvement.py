"""Evidence-backed Criterion 4 narrative for the UTRGV BSME edition.

The submitted Criterion 4 document controls values and status language when
the detailed drafts differ.  The source PDFs and implementation briefs supply
process detail and intervention mechanics; they are not treated as proof of
post-intervention effectiveness on their own.

This module intentionally contains presentation data only.  It does not read
or write the operational assessment database, so deploying a narrative update
cannot alter faculty-entered evidence.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


_STORY: dict[str, Any] = {
    "cycle_label": "2020–2026 review cycle · Criterion 4",
    "title": "Evidence, faculty action, reassessment—and an honest next decision",
    "lede": (
        "UTRGV Mechanical Engineering closes the continuous-improvement loop by "
        "preserving a visible chain from PI-level evidence to faculty evaluation, "
        "the change actually implemented, comparable reassessment, and the next "
        "decision. The program records successful, partial, and still-open results "
        "with the same discipline."
    ),
    "evidence_note": (
        "The submitted 2026 Criterion 4 narrative is the controlling source when "
        "draft figures differ. Historical results in these documents are not "
        "campus-disaggregated; campus comparisons belong in the portal Analytics "
        "view and are not inferred here."
    ),
    "summary_cards": [
        {
            "value": "1",
            "label": "Verified course-level loop",
            "detail": "MECE 3320 / SLO-6 has a multi-term comparison under progressively harder work.",
            "tone": "positive",
        },
        {
            "value": "3",
            "label": "Faculty-approved overlays deployed",
            "detail": "Problem Analysis, Concept Development, and Audience Adaptation.",
            "tone": "context",
        },
        {
            "value": "2",
            "label": "First post-deployment comparisons",
            "detail": "SLO-2 is promising; SLO-3 is mixed and has a defined adjustment path.",
            "tone": "watch",
        },
        {
            "value": "1",
            "label": "Program-wide comparison in flight",
            "detail": "SLO-1 is deployed, but a multi-term closed-loop conclusion is not yet supported.",
            "tone": "attention",
        },
    ],
    "methodology": {
        "framework": "Analysis → Intervention → Comparison (AIC)",
        "attainment": "EP% = Expert + Practitioner on the EPAN rubric",
        "target": "EP% ≥ 70% for each direct assessment measure",
        "cutoff": "Submitted evidence through Fall 2025, plus Spring 2026 SLO-1 deployment status",
        "caution": (
            "A fitted trend or one post-deployment term is descriptive evidence, "
            "not proof that an intervention caused the result. “Verified” is "
            "reserved for a documented, comparable reassessment with a faculty "
            "decision; incomplete and mixed outcomes remain visibly open."
        ),
    },
    "loop_steps": [
        {
            "number": "01",
            "title": "Assess",
            "text": (
                "Faculty score existing course artifacts at the PI level with EPAN "
                "and retain the result, context, and observation in the portal."
            ),
        },
        {
            "number": "02",
            "title": "Analyze and decide",
            "text": (
                "SLO committees triangulate direct evidence, faculty observations, "
                "exit-survey results, and stakeholder input before recommending action."
            ),
        },
        {
            "number": "03",
            "title": "Implement",
            "text": (
                "The faculty approve an owner, scope, timeline, and measurable change. "
                "Targeted overlays preserve normal grading and comparable artifacts."
            ),
        },
        {
            "number": "04",
            "title": "Compare and act again",
            "text": (
                "The same PI is reassessed. Faculty retain a successful practice, "
                "adapt a partial one, or investigate before selecting another change."
            ),
        },
    ],
    "cases": [
        {
            "slug": "slo6-mece3320-verified-loop",
            "outcome": "SLO-6 · Experimentation and data analysis",
            "title": "MECE 3320: improvement sustained under more demanding artifacts",
            "status": "Verified course-level loop",
            "status_key": "verified",
            "scope": "MECE 3320, Spring 2022–Spring 2025; normal course operation (Tier 2)",
            "conclusion": (
                "Attainment moved 68% → 74%, from below target to above target, while the rubric "
                "was tightened and the assessed work became progressively more complex. "
                "The fitted course trend was +1.60 pp/term. This is the strongest completed "
                "loop in the submitted chapter."
            ),
            "chain": [
                {
                    "stage": "Analysis",
                    "title": "A localized below-target baseline",
                    "text": (
                        "MECE 3320 SLO-6 attainment was 68% in Spring 2022, below the "
                        "70% standard. The signal was sufficiently localized for the "
                        "instructor and SLO chair to respond through normal course operation."
                    ),
                    "items": [],
                },
                {
                    "stage": "Intervention",
                    "title": "Progressively stronger evidence tasks",
                    "text": (
                        "The course retained a stable rubric while deliberately increasing "
                        "the rigor and integration of the assessed artifacts."
                    ),
                    "items": [
                        "Spring 2023: tightened rubric application on the existing artifacts.",
                        "Spring 2024: more complex sensor, bias-removal, and noise-filtering work.",
                        "Spring 2025: multi-order models, comprehensive uncertainty, and large-dataset RMS work.",
                    ],
                },
                {
                    "stage": "Comparison",
                    "title": "A four-term, comparable trajectory",
                    "text": (
                        "The sequence was 68% → 71% → 69% → 74%. The submitted analysis "
                        "reports a +1.60 percentage-point-per-term course trend, p < .001, "
                        "with no detected Bloom-level concentration (Kruskal–Wallis p = 1.000)."
                    ),
                    "items": [],
                },
                {
                    "stage": "Decision",
                    "title": "Retain and continue monitoring",
                    "text": (
                        "Faculty documented a course-level closed loop: performance is above "
                        "target under the most demanding artifact set, so no department-wide "
                        "AFI was required."
                    ),
                    "items": [],
                },
            ],
            "metrics": [
                {
                    "period": "Spring 2022",
                    "measure": "MECE 3320 SLO-6 course attainment",
                    "value": "68%",
                    "target": "70%",
                    "interpretation": "Below target; course-level response initiated.",
                },
                {
                    "period": "Spring 2023",
                    "measure": "Same outcome after rubric tightening",
                    "value": "71%",
                    "target": "70%",
                    "interpretation": "Crossed target.",
                },
                {
                    "period": "Spring 2024",
                    "measure": "Same outcome with higher artifact complexity",
                    "value": "69%",
                    "target": "70%",
                    "interpretation": "One-point marginal dip under increased difficulty.",
                },
                {
                    "period": "Spring 2025",
                    "measure": "Same outcome with integrative artifacts",
                    "value": "74%",
                    "target": "70%",
                    "interpretation": "Sustained above target under the strongest task set.",
                },
            ],
            "decision": (
                "The course-level practice is retained. The four-term comparison and "
                "broad Bloom-level result support a verified Tier-2 loop without a formal AFI."
            ),
            "next_step": (
                "Continue routine portal monitoring and close the separate MECE 2140 "
                "SLO-6 coverage gap under NX-03."
            ),
            "sources": [
                {
                    "document": "ABET_Criterion_4_2026_Isaac_Submitted.docx",
                    "reference": "§4.B.3.6, pp. 4-31–4-34",
                },
                {
                    "document": "ABET_Criterion_4C_Revised.pdf",
                    "reference": "Criterion 4 detailed evidence, pp. 35–55 and 97–98",
                },
            ],
        },
        {
            "slug": "slo2-concept-development-first-comparison",
            "outcome": "SLO-2 · Engineering design within constraints",
            "title": "Concept Development Overlay: targeted Create-level performance above standard",
            "status": "Positive first-term evidence — monitoring continues",
            "status_key": "monitoring",
            "scope": "MECE 4361 Senior Design I; Spring 2024–Fall 2025",
            "conclusion": (
                "The first post-deployment term met the standard on all three PIs, "
                "including the targeted PI-1 Create trajectory of 65% → 80% → 83%. "
                "Because Spring 2025 had "
                "already recovered before deployment, the result is promising evidence—"
                "not a claim that one term proves causation or sustained effectiveness."
            ),
            "chain": [
                {
                    "stage": "Analysis",
                    "title": "A material capstone design dip",
                    "text": (
                        "MECE 4361 fell from 93% in Spring 2023 to 65% in Spring 2024. "
                        "Faculty identified weak movement from problem definition to varied, "
                        "feasible concepts linked to requirements and constraints."
                    ),
                    "items": [],
                },
                {
                    "stage": "Faculty decision",
                    "title": "Formalize a practice despite pre-AFI recovery",
                    "text": (
                        "Spring 2025 recovered to 88% before approval, but faculty treated "
                        "the prior capstone dip as important enough to standardize concept "
                        "development. The overlay was approved in August/September 2025."
                    ),
                    "items": [],
                },
                {
                    "stage": "Intervention",
                    "title": "Concept generation became observable",
                    "text": (
                        "The Fall 2025 Midterm Poster required at least six diverse concepts, "
                        "at least one structured creativity method, feasibility comments, "
                        "and explicit linkage to requirements and constraints."
                    ),
                    "items": [
                        "Structured methods include morphological charts, 6-3-5, or SCAMPER.",
                        "The existing Senior Design I grading sheet and artifact were retained.",
                    ],
                },
                {
                    "stage": "Comparison",
                    "title": "All three Fall 2025 PIs above 70%",
                    "text": (
                        "Fall 2025 PI results were 83% Create, 73% Evaluate, and 83% Analyze; "
                        "the course average was approximately 80%."
                    ),
                    "items": [],
                },
            ],
            "metrics": [
                {
                    "period": "Spring 2024",
                    "measure": "PI-1 Create",
                    "value": "65%",
                    "target": "70%",
                    "interpretation": "Below target; the diagnostic dip.",
                },
                {
                    "period": "Spring 2025",
                    "measure": "PI-1 Create",
                    "value": "80%",
                    "target": "70%",
                    "interpretation": "Pre-intervention recovery; not attributed to the overlay.",
                },
                {
                    "period": "Fall 2025",
                    "measure": "PI-1 Create after deployment",
                    "value": "83%",
                    "target": "70%",
                    "interpretation": "First comparison above target under the overlay.",
                },
                {
                    "period": "Fall 2025",
                    "measure": "PI-2 Evaluate / PI-3 Analyze",
                    "value": "73% / 83%",
                    "target": "70%",
                    "interpretation": "Both supporting PIs above target.",
                },
            ],
            "decision": (
                "Retain the Concept Development Overlay while collecting additional terms. "
                "The first comparison supports continuation, but does not yet establish "
                "multi-term effectiveness."
            ),
            "next_step": (
                "Reassess under AS-05 through Spring 2027 and complete the multi-term review "
                "at the Spring 2027 faculty retreat."
            ),
            "sources": [
                {
                    "document": "ABET_Interventions.pdf",
                    "reference": "original suggested SLO-2 intervention, p. 3",
                },
                {
                    "document": "SLO2_Intervention.pdf",
                    "reference": "implemented Concept Development rubric, p. 1",
                },
                {
                    "document": "ABET_Criterion_4_2026_Isaac_Submitted.docx",
                    "reference": "§4.B.3.2, pp. 4-21–4-24",
                },
            ],
        },
        {
            "slug": "slo3-audience-adaptation-mixed-comparison",
            "outcome": "SLO-3 · Communication",
            "title": "Audience Adaptation Overlay: presentation recovered; writing remained open",
            "status": "Mixed evidence — adaptation required",
            "status_key": "attention",
            "scope": "MECE 4361 and communication-intensive courses; Spring 2024–Fall 2025",
            "conclusion": (
                "The first comparison separates what worked from what did not: the "
                "presentation PI recovered 61% → 92%, while PI-3: 60% technical writing "
                "remained below target. The department therefore continued the successful element "
                "and identified the artifact requiring explicit extension and calibration."
            ),
            "chain": [
                {
                    "stage": "Analysis",
                    "title": "Audience and professional-context weakness",
                    "text": (
                        "The Spring 2024 program result was 71.7%, with MECE 4361 PI-2 "
                        "presentation at 61%. Faculty also observed inconsistent adaptation "
                        "for technical, managerial, and public audiences."
                    ),
                    "items": [],
                },
                {
                    "stage": "Intervention",
                    "title": "The same work for two audiences",
                    "text": (
                        "Beginning Fall 2025, lab and project courses added a managerial or "
                        "sponsor-facing paragraph, slide, or summary alongside the technical "
                        "version, with explicit attention to tone, structure, visuals, and "
                        "professional context."
                    ),
                    "items": [
                        "Direct target: audience adaptation (PI-4).",
                        "Reinforced measures: presentation (PI-2) and technical writing (PI-3).",
                    ],
                },
                {
                    "stage": "Comparison",
                    "title": "A deliberately mixed first result",
                    "text": (
                        "In Fall 2025, MECE 4361 graphics was 79%, presentation recovered "
                        "from 61% to 92%, and technical writing was 60%; the course average "
                        "was approximately 77%."
                    ),
                    "items": [],
                },
                {
                    "stage": "Adaptation",
                    "title": "Extend the practice to the unresolved artifact",
                    "text": (
                        "Faculty identified the SD-I Technical Report as the next calibration "
                        "site so the two-audience expectation directly reaches the PI-3 writing artifact."
                    ),
                    "items": [],
                },
            ],
            "metrics": [
                {
                    "period": "Spring 2024",
                    "measure": "PI-2 Presentation",
                    "value": "61%",
                    "target": "70%",
                    "interpretation": "Below target; intervention trigger.",
                },
                {
                    "period": "Fall 2025",
                    "measure": "PI-2 Presentation after deployment",
                    "value": "92%",
                    "target": "70%",
                    "interpretation": "Strong first-term recovery.",
                },
                {
                    "period": "Fall 2025",
                    "measure": "PI-3 Technical writing",
                    "value": "60%",
                    "target": "70%",
                    "interpretation": "Still below target; active adaptation item.",
                },
                {
                    "period": "Fall 2025",
                    "measure": "MECE 4361 course average",
                    "value": "≈77%",
                    "target": "70%",
                    "interpretation": "Average met target but did not erase the PI-3 gap.",
                },
            ],
            "decision": (
                "Retain the two-audience practice because the directly reinforced "
                "presentation measure recovered, and adapt its reach because technical "
                "writing did not. The loop remains open for the unresolved PI-3 artifact."
            ),
            "next_step": (
                "Calibrate and extend the expectation to the SD-I Technical Report, then "
                "reassess under AS-06 through the Spring 2027 multi-term review."
            ),
            "sources": [
                {
                    "document": "ABET_Interventions.pdf",
                    "reference": "original suggested SLO-3 intervention, p. 4",
                },
                {
                    "document": "SLO3_Intervention.pdf",
                    "reference": "implemented Audience Adaptation rubric, p. 1",
                },
                {
                    "document": "ABET_Criterion_4_2026_Isaac_Submitted.docx",
                    "reference": "§4.B.3.3, pp. 4-24–4-27",
                },
            ],
        },
        {
            "slug": "slo1-problem-analysis-reassessment",
            "outcome": "SLO-1 · Problem analysis",
            "title": "Problem Analysis Overlay: implementation complete, comparison still accruing",
            "status": "Implementation complete — verification in flight",
            "status_key": "open",
            "scope": "Program-wide overlay; trigger evidence in MECE 2302, Spring 2022–Spring 2026",
            "conclusion": (
                "The intervention is documented and the first Spring 2026 record is in "
                "the portal, but the submitted evidence does not report that value and the "
                "Fall-only courses have not yet supplied the first full program-wide comparison. "
                "SLO-1 has not yet been declared closed; no success or failure is inferred."
            ),
            "chain": [
                {
                    "stage": "Analysis",
                    "title": "A persistent MECE 2302 decline",
                    "text": (
                        "The submitted trajectory was 76% → 69% → 60% → 39% from Spring "
                        "2022 through Spring 2025. The reported slope was −11.03 percentage "
                        "points per term (−11.03 pp/term, p = .025), making MECE 2302 the dominant SLO-1 signal."
                    ),
                    "items": [
                        "MECE 2340 recovered 46% → 58% → 89%.",
                        "Upper-division SLO-1 evidence was generally stable or volatile rather than persistently declining.",
                    ],
                },
                {
                    "stage": "Faculty decision",
                    "title": "Standardize analysis without replacing normal grading",
                    "text": (
                        "Faculty approved the overlay in August/September 2025 and reviewed "
                        "implementation in December 2025. Deployment was timed for Spring 2026 "
                        "because the primary trigger courses are Spring-only."
                    ),
                    "items": [],
                },
                {
                    "stage": "Intervention",
                    "title": "Given–Find–Assumptions–Approach–Units",
                    "text": (
                        "Each contributing course selects one aligned assignment or exam item "
                        "and applies common expectations for identifying, formulating, and "
                        "solving the problem, including assumptions, decomposition, units, "
                        "reasonableness, and validation."
                    ),
                    "items": [],
                },
                {
                    "stage": "Comparison",
                    "title": "First record available; full comparison pending",
                    "text": (
                        "A Spring 2026 MECE 2302 record exists, but the supplied Criterion 4 "
                        "documents do not state its numerical result. Fall 2026 supplies the "
                        "first post-deployment evidence from the Fall-only courses."
                    ),
                    "items": [],
                },
            ],
            "metrics": [
                {
                    "period": "Spring 2022",
                    "measure": "MECE 2302 SLO-1 attainment",
                    "value": "76%",
                    "target": "70%",
                    "interpretation": "Above target at the start of the trigger trajectory.",
                },
                {
                    "period": "Spring 2023",
                    "measure": "MECE 2302 SLO-1 attainment",
                    "value": "69%",
                    "target": "70%",
                    "interpretation": "Below target.",
                },
                {
                    "period": "Spring 2024",
                    "measure": "MECE 2302 SLO-1 attainment",
                    "value": "60%",
                    "target": "70%",
                    "interpretation": "Decline persisted.",
                },
                {
                    "period": "Spring 2025",
                    "measure": "MECE 2302 SLO-1 attainment",
                    "value": "39%",
                    "target": "70%",
                    "interpretation": "Primary intervention trigger.",
                },
                {
                    "period": "Spring 2026",
                    "measure": "First post-deployment MECE 2302 record",
                    "value": "Recorded; value not stated in supplied narrative",
                    "target": "70%",
                    "interpretation": "Not treated as zero and not used to declare closure.",
                },
            ],
            "decision": (
                "Keep the overlay in place and reserve judgment. The evidence supports "
                "implementation, not yet a multi-term outcome conclusion."
            ),
            "next_step": (
                "Conduct the Fall 2026 interim comparison when MECE 3315, 3360, 3450, "
                "and 4350 contribute post-deployment evidence; complete the full review in Spring 2027."
            ),
            "sources": [
                {
                    "document": "ABET_Interventions.pdf",
                    "reference": "original suggested SLO-1 intervention, p. 2",
                },
                {
                    "document": "SLO1_Intervention.pdf",
                    "reference": "implemented Problem Analysis rubric, p. 1",
                },
                {
                    "document": "ABET_Criterion_4_2026_Isaac_Submitted.docx",
                    "reference": "§4.B.3.1, pp. 4-17–4-21",
                },
            ],
        },
    ],
    "proposal_comparison": [
        {
            "outcome": "SLO-1",
            "need": (
                "Students could solve routine problems but often omitted formulation, "
                "decomposition, assumptions, justification, and reasonableness checks."
            ),
            "proposed": (
                "A common Given–Find–Assumptions–Approach–Units checklist, structured "
                "justification, and progressive expectations by course level."
            ),
            "implemented": (
                "One aligned item in each contributing course, scored 0–100 and mapped "
                "to EPAN across Identify, Formulate, and Solve criteria with lower- and upper-level descriptors."
            ),
            "boundary": (
                "The rubric is deployed; a program-wide multi-term result is not yet claimed."
            ),
        },
        {
            "outcome": "SLO-2",
            "need": (
                "Senior-design teams needed clearer, more varied concept generation and "
                "stronger linkage to requirements, constraints, and feasibility."
            ),
            "proposed": (
                "Problem-definition rubric, concept-development rubric, and a decision "
                "matrix with at least five criteria."
            ),
            "implemented": (
                "The supplied implementation brief documents the Concept Development "
                "component: at least six concepts, one structured method, feasibility notes, "
                "and requirements/constraints linkage in the Midterm Poster."
            ),
            "boundary": (
                "The portal does not claim that the separate problem-definition rubric or "
                "five-criterion decision matrix was deployed without additional evidence."
            ),
        },
        {
            "outcome": "SLO-3",
            "need": (
                "Students needed to tailor technical content, tone, structure, visuals, "
                "and professional implications to different audiences."
            ),
            "proposed": (
                "Audience-adaptation rubric, combined technical/professional deliverables, "
                "and shared faculty exemplars."
            ),
            "implemented": (
                "Two-audience technical plus managerial/sponsor deliverables, scored for "
                "clarity, audience fit, and integration of cost, risk, schedule, safety, "
                "ethics, sustainability, and stakeholder context."
            ),
            "boundary": (
                "The supplied implementation brief does not establish that shared faculty "
                "exemplars were deployed; the portal does not list them as completed."
            ),
        },
    ],
    "response_tiers": [
        {
            "tier": "Tier 1",
            "title": "Formal department-level AFI",
            "when_used": (
                "The pattern is persistent or broad, the diagnosis is defensible, and a "
                "specific measurable intervention can be assigned."
            ),
            "examples": "SLO-1 Problem Analysis, SLO-2 Concept Development, and SLO-3 Audience Adaptation.",
        },
        {
            "tier": "Tier 2",
            "title": "Closure through normal course operation",
            "when_used": (
                "The signal is localized and the instructor of record plus SLO chair can "
                "adjust the course without a department-wide AFI."
            ),
            "examples": "MECE 3320 SLO-6 verified loop and its parallel SLO-5 trajectory.",
        },
        {
            "tier": "Tier 3",
            "title": "Structured investigation before action",
            "when_used": (
                "Several explanations remain plausible and acting too early risks changing "
                "the wrong part of the curriculum or rubric."
            ),
            "examples": "SLO-5 MECE 4361 PI dips and the isolated MECE 1221 SLO-2 point.",
        },
    ],
    "monitoring": [
        {
            "outcome": "SLO-1",
            "status": "Overlay deployed; no multi-term conclusion declared.",
            "decision": "AS-04 interim Fall 2026; full review Spring 2027.",
        },
        {
            "outcome": "SLO-2",
            "status": "First comparison positive; sustained effectiveness not yet established.",
            "decision": "AS-05 comparison through Spring 2027.",
        },
        {
            "outcome": "SLO-3",
            "status": "Presentation recovered; technical writing remains below target.",
            "decision": "AS-06 calibration/extension and Spring 2027 review.",
        },
        {
            "outcome": "SLO-4",
            "status": "All assessing-course averages remained above target; no AFI required.",
            "decision": "Monitor the current-issues dimension under NX-08.",
        },
        {
            "outcome": "SLO-5",
            "status": "MECE 3320 improved; capstone PI-2/PI-5 signals remain unresolved.",
            "decision": "Tier-3 investigation under NX-04; SD-II review under NX-01.",
        },
        {
            "outcome": "SLO-6",
            "status": "MECE 3320 course-level loop verified; other coverage remains tracked.",
            "decision": "Routine monitoring plus MECE 2140 coverage work under NX-03.",
        },
        {
            "outcome": "SLO-7",
            "status": "Strong SD-I evidence but a genuine SD-II PI-2 weakness.",
            "decision": "Course review under NX-01 and earlier-pipeline coverage under NX-05.",
        },
    ],
    "sources": [
        {
            "document": "ABET_Criterion_4_2026_Isaac_Submitted.docx",
            "role": "Controlling submitted Criterion 4 narrative and corrected case-study values/status language.",
            "references": "especially §4.B, pp. 4-15–4-44",
        },
        {
            "document": "ABET_Criterion_4C_Revised.pdf",
            "role": "Detailed governance, prioritization, Decision Log, evidence flow, and honest-accounting record.",
            "references": "especially pp. 25–55, 81–82, 93–98, and 166–170",
        },
        {
            "document": "ABET_Criterion_4B_Revised.pdf",
            "role": "Corroborating detailed direct-measure and continuous-improvement evidence.",
            "references": "especially pp. 24–54, 80–81, and 92–97",
        },
        {
            "document": "ABET_Interventions.pdf",
            "role": "Original suggested departmental interventions and pre-adoption evidence through Spring 2025.",
            "references": "SLO-1, SLO-2, and SLO-3 proposals on pp. 2–4",
        },
        {
            "document": "SLO1_Intervention.pdf",
            "role": "Implemented Problem Analysis overlay mechanics and EPAN performance descriptors.",
            "references": "p. 1",
        },
        {
            "document": "SLO2_Intervention.pdf",
            "role": "Implemented Concept Development criteria in Senior Design I.",
            "references": "p. 1",
        },
        {
            "document": "SLO3_Intervention.pdf",
            "role": "Implemented Audience Adaptation criteria for communication-intensive courses.",
            "references": "p. 1",
        },
    ],
}


def get_utrgv_continuous_improvement_story() -> dict[str, Any]:
    """Return an isolated copy of the visit-ready Criterion 4 narrative."""

    return deepcopy(_STORY)
