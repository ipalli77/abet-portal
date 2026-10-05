"""Evidence navigation, not an accreditation verdict or an invented evidence set."""
from collections import defaultdict
from datetime import date
import json

CRITERIA_URL = 'https://www.abet.org/accreditation/accreditation-criteria/criteria-for-accrediting-engineering-programs-2026-2027/'
# Brief navigation prompts; the linked official criteria control the requirements.
CRITERIA = (
    ('1', 'Students', 'Entry & progress', 'How am I admitted, advised, and supported toward completion?',
     'Admissions and transfer policies; advising records; degree checks.'),
    ('2', 'Program objectives', 'Professional direction', 'What does the program prepare me to achieve after graduation?',
     'Published objectives; constituency input; periodic review minutes.'),
    ('3', 'Student outcomes', 'Learning', 'What should I be able to do by graduation?',
     'Outcome definitions; curriculum mapping; assessed work.'),
    ('4', 'Continuous improvement', 'Better learning', 'How does the department use evidence to improve my education?',
     'Results; faculty decisions; implemented changes; reassessment.'),
    ('5', 'Curriculum', 'Coursework & design', 'How do my courses prepare me for engineering practice?',
     'Degree plan; credit analysis; syllabi; culminating design evidence.'),
    ('6', 'Faculty', 'Teaching & mentoring', 'Who teaches and guides me?',
     'Faculty qualifications; workload; professional development.'),
    ('7', 'Facilities', 'Tools & spaces', 'What resources support my learning?',
     'Laboratories; safety guidance; equipment maintenance; computing resources.'),
    ('8', 'Institutional support', 'Program continuity', 'How is my program sustained?',
     'Resources; staffing; leadership; institutional support.'),
    ('ME', 'Mechanical engineering', 'Engineering practice', 'How do I learn to model, design, and realize physical systems?',
     'Thermal/mechanical coverage and depth; mathematics applications; faculty currency.'),
)
RESOURCE_KINDS = {'syllabus': 'Syllabus', 'assignment': 'Assignment / exam / lab',
    'rubric': 'Scoring rubric', 'student_work': 'Anonymized student work',
    'minutes': 'Faculty decision / minutes', 'campus_protocol': 'Campus assessment protocol',
    'report': 'Project / technical report', 'photo': 'Project photograph', 'other': 'Supporting document'}
STAGES = {'finding': 'Finding', 'decision': 'Faculty decision', 'implementation': 'Implemented change',
          'reassessment': 'Reassessment', 'follow_up': 'Follow-up'}
KINDS = {'resource': 'Supporting document', 'plan': 'Assessment plan',
         'milestone': 'Improvement milestone', 'project': 'Capstone project'}


def decode_entry(row):
    item = dict(row)
    item['data'] = json.loads(item['payload_json'])
    return item


def assessment_matrix(courses, outcomes, records, plans):
    groups = defaultdict(lambda: {'observed': {}, 'plans': []})
    for record in records:
        cell = groups[(record['course_id'], record['outcome_id'])]
        pi = cell['observed'].setdefault(record['indicator_id'], {
            'id': record['indicator_id'], 'code': record['indicator_code'], 'count': 0, 'campuses': set()})
        pi['count'] += 1
        pi['campuses'].add(record['campus'])
    for plan in plans:
        groups[(plan['course_id'], plan['data']['outcome_id'])]['plans'].append(plan)
    return [{'course': dict(course), 'cells': [
        {'outcome': dict(outcome), 'observed': list(groups[(course['id'], outcome['id'])]['observed'].values()),
         'plans': groups[(course['id'], outcome['id'])]['plans']}
        for outcome in outcomes]} for course in courses]


def campus_coverage(records):
    grouped = defaultdict(lambda: defaultdict(list))
    for row in records:
        if row['campus'] in ('Edinburg', 'Brownsville'):
            grouped[row['course_code']][row['campus']].append(row)
    result = []
    for code, campuses in sorted(grouped.items()):
        cells = []
        for campus in ('Edinburg', 'Brownsville'):
            rows = campuses[campus]
            cells.append({'campus': campus, 'count': len(rows),
                          'mean': sum(r['attainment'] for r in rows) / len(rows) if rows else None,
                          'terms': sorted({(r['term_order'], r['term_label']) for r in rows}),
                          'outcomes': sorted({r['outcome_code'] for r in rows}),
                          'course_id': rows[0]['course_id'] if rows else None})
        result.append({'code': code, 'cells': cells})
    return result


def readiness_checks(records, attachments, entries, actions, sources, path_check):
    """A preparation list, not a computed ABET compliance score. No HTTP probes."""
    attached = {a['assessment_id'] for a in attachments}
    checks = []
    def add(category, title, detail, record_id=None, entry_id=None):
        checks.append(dict(category=category, title=title, detail=detail,
                           record_id=record_id, entry_id=entry_id))
    for record in records:
        if record['id'] not in attached:
            add('Artifacts', record['course_code'], 'No assessment attachment linked to this approved record.', record['id'])
        if record['indicator_code'].startswith('UNMAPPED-'):
            add('Mapping', record['course_code'], 'Performance indicator needs confirmation.', record['id'])
        if not record['observations'].strip():
            add('Interpretation', record['course_code'], 'Faculty interpretation is not recorded.', record['id'])
    for item in attachments:
        if item['storage_key'] and not path_check(item['storage_key']):
            add('Files', item['title'], 'Attachment file is missing or outside the protected storage folder.', item['assessment_id'])
        if item['source_url']:
            add('External links', item['title'], 'Open and verify this external link manually; availability is not automatically checked.', item['assessment_id'])
    for entry in entries:
        data = entry['data']
        if entry['status'] == 'draft':
            add('Drafts', entry['title'], 'Not included in published evidence or visit editions.', entry_id=entry['id'])
        if entry['kind'] == 'resource':
            if data.get('storage_key') and not path_check(data['storage_key']):
                add('Files', entry['title'], 'Supporting document file is missing.', entry_id=entry['id'])
            if data.get('source_url'):
                add('External links', entry['title'], 'External link requires manual verification.', entry_id=entry['id'])
        if entry['kind'] == 'milestone' and data.get('stage') == 'follow_up' and data.get('due_on'):
            if data['due_on'] < date.today().isoformat() and not data.get('completed'):
                add('Follow-up', entry['title'], 'The recorded next-review date has passed; confirm the follow-up.', entry_id=entry['id'])
    for action in actions:
        if action.get('due_on') and action['due_on'] < date.today().isoformat() and action['status'] not in ('verified', 'completed', 'cancelled'):
            add('Actions', action['title'], 'Open action is past its recorded due date.')
    for source in sources:
        if not source['available']:
            add('Files', source['document'], 'Historical source file is not installed.')
    return checks
