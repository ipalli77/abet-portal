"""Course dossiers and a protected, versioned accreditation evidence workspace.

No new evaluator identity or permission is introduced. Operational assessment
records remain the source of numerical results; supplemental material is
explicitly authored and published by existing program managers.
"""
from collections import Counter
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlparse, urlencode
from zipfile import ZipFile, ZIP_DEFLATED
import io
import json
import secrets
import base64

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, send_file, session, url_for
from werkzeug.utils import secure_filename

from . import routes as core
from .db import get_db
from .security import audit, login_required, require_program, role_required
from .curriculum import CASE_COURSES, curriculum_overview
from .presentation import matched_campus_comparison, SOURCE_FILES
from .visit_content import (CRITERIA, CRITERIA_URL, KINDS, RESOURCE_KINDS, STAGES,
                            assessment_matrix, campus_coverage, decode_entry, readiness_checks)

bp = Blueprint('visit', __name__)
MANAGERS = core.MANAGER_ROLES
SAFE_RECORD_FIELDS = ('id', 'record_version', 'course_id', 'course_code', 'course_name', 'campus',
    'term_id', 'term_label', 'term_order', 'outcome_id', 'outcome_code', 'outcome_label',
    'indicator_id', 'indicator_code', 'indicator_label', 'assessment_tool', 'method', 'bloom_level',
    'attainment', 'target', 'result_basis', 'sample_size', 'expert_percent', 'practitioner_percent',
    'apprentice_percent', 'novice_percent', 'observations', 'action_notes', 'status', 'updated_at',
    'admin_revision_count', 'admin_change_note', 'admin_changed_by', 'admin_changed_at')


def manager():
    return g.membership['role'] in MANAGERS


def storage_path(key):
    root = Path(current_app.config['UPLOAD_FOLDER']).resolve()
    candidate = (root / str(key)).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        return None
    return candidate


def can_read(entry, program_id):
    if entry['program_id'] != program_id:
        return False
    if manager():
        return True
    if entry['status'] != 'published' or not entry['course_id']:
        return False
    pairs = core._faculty_course_campus_pairs(program_id)
    if current_app.config.get('EDITION') != 'utrgv_mece':
        return entry['course_id'] in (core._faculty_course_ids(program_id) or set())
    required = ('Edinburg', 'Brownsville') if entry['campus'] == 'Both' else (entry['campus'],)
    return all((entry['course_id'], campus) in (pairs or set()) for campus in required)


def entries(program_id, *, kind=None, published=True, course_id=None):
    rows = get_db().execute('SELECT * FROM portal_entries WHERE program_id=? ORDER BY updated_at DESC,id DESC', (program_id,))
    return [entry for row in rows if can_read(entry := decode_entry(row), program_id)
            and (not kind or entry['kind'] == kind)
            and (entry['status'] == 'published' if published else entry['status'] != 'archived')
            and (course_id is None or entry['course_id'] == course_id)]


def entry_by_id(entry_id, program_id, kind=None):
    row = get_db().execute('SELECT * FROM portal_entries WHERE id=? AND program_id=?', (entry_id, program_id)).fetchone()
    if not row:
        abort(404)
    entry = decode_entry(row)
    if not can_read(entry, program_id) or (kind and entry['kind'] != kind):
        abort(404)
    return entry


def approved_context(course_id=None):
    program = require_program()
    filters = core._analysis_filter_context(program['id'])
    if filters['evidence_scope'] != 'approved':
        abort(400, 'Evidence pages contain approved assessments only.')
    where, params = filters['where'], filters['params']
    if course_id is not None:
        where += ' AND ar.course_id=?'
        params = (*params, course_id)
    records = [dict(row) for row in core._record_query(program['id'], where, params)]
    return program, filters, records


def course_for_user(program_id, course_id):
    course = get_db().execute('SELECT * FROM courses WHERE id=? AND program_id=?', (course_id, program_id)).fetchone()
    allowed = core._faculty_course_ids(program_id)
    if not course or (allowed is not None and course_id not in allowed):
        abort(404)
    return dict(course)


def linked_cases(course_code=None):
    story = core._continuous_improvement_story_for_manager()
    return [case for case in (story or {}).get('cases', [])
            if course_code is None or course_code in CASE_COURSES.get(case['slug'], {})]


def scoped_actions(program_id, course_id=None):
    sql_scope, values = core._faculty_record_scope_sql(program_id, 'ar.course_id', 'ar.campus')
    if course_id is not None:
        sql_scope += ' AND ar.course_id=?'
        values = (*values, course_id)
    return [dict(row) for row in get_db().execute(
        f'''SELECT ia.*,ar.course_id,ar.campus FROM improvement_actions ia
            LEFT JOIN assessment_records ar ON ar.id=ia.assessment_id AND ar.program_id=ia.program_id
            WHERE ia.program_id=?{sql_scope} ORDER BY ia.created_at DESC''', (program_id, *values))]


@bp.app_context_processor
def helpers():
    def course_url(course_id, **updates):
        pairs = [(key,value) for key in request.args for value in request.args.getlist(key)
                 if key not in {'course_id',*updates}]
        for key,value in updates.items():
            if value:
                pairs.extend((key,item) for item in value) if isinstance(value,(list,tuple,set)) else pairs.append((key,value))
        return url_for('visit.course',course_id=course_id)+('?' + urlencode(pairs) if pairs else '')
    return {'resource_kinds': RESOURCE_KINDS, 'milestone_stages': STAGES,
            'entry_kinds': KINDS, 'criterion_definitions': CRITERIA, 'course_url':course_url}


@bp.get('/courses')
@login_required
def courses():
    program, filters, records = approved_context()
    counts = Counter(r['course_id'] for r in records)
    return render_template('visit_courses.html', program=program, courses=filters['dimensions']['courses'], counts=counts)


@bp.get('/courses/<int:course_id>')
@login_required
def course(course_id):
    program, filters, records = approved_context(course_id)
    item = course_for_user(program['id'], course_id)
    resources = entries(program['id'], kind='resource', course_id=course_id)
    # Supplemental documents have their own labeled campus/date scope; apply
    # selected campus filters to them, never label them as term-filtered results.
    selected = set(filters['selected_campuses'])
    if selected:
        resources = [r for r in resources if r['campus'] in selected or r['campus'] == 'Both']
    missing = [RESOURCE_KINDS[kind] for kind in ('syllabus','assignment','rubric','student_work')
               if not any(r['data'].get('document_kind') == kind for r in resources)]
    return render_template('visit_course.html', program=program, course=item, records=records,
        resources=resources, missing=missing, filters=filters,
        overview=core._overview(records, program['id']), cases=linked_cases(item['code']),
        attachments=core._record_evidence(program['id'], [r['id'] for r in records]),
        milestones=entries(program['id'], kind='milestone', course_id=course_id),
        plans=entries(program['id'], kind='plan', course_id=course_id),
        actions=scoped_actions(program['id'], course_id),
        faculty=sorted({r['collector_name'] for r in records}), is_manager=manager(),
        packet_url=url_for('visit.course_packet',course_id=course_id)+'?'+urlencode([
            (key,value) for key in request.args for value in request.args.getlist(key) if key!='course_id']))


@bp.get('/assessment-map')
@login_required
def mapping():
    program, filters, records = approved_context()
    courses = filters['dimensions']['courses']
    selected_courses = set(filters['selected_course_ids'])
    if selected_courses:
        courses = [c for c in courses if c['id'] in selected_courses]
    outcomes = filters['dimensions']['outcomes']
    plans = entries(program['id'], kind='plan')
    selected_campuses = set(filters['selected_campuses'])
    if selected_campuses:
        plans = [p for p in plans if p['campus'] in selected_campuses]
    matrix = assessment_matrix(courses, outcomes, records, plans)
    improvement_ids = {action['course_id'] for action in scoped_actions(program['id'])
                       if action['course_id'] and action['status']!='cancelled'}
    improvement_ids.update(item['course_id'] for item in entries(program['id'],kind='milestone'))
    historical_codes = {code for case in linked_cases() for code in CASE_COURSES.get(case['slug'],{})}
    for row in matrix:
        row['improvement'] = row['course']['id'] in improvement_ids or row['course']['code'] in historical_codes
    return render_template('visit_map.html', program=program, matrix=matrix, outcomes=outcomes,
                           filters=filters, is_manager=manager())


@bp.get('/criteria')
@role_required('coordinator')
def criteria():
    program = require_program()
    documents = entries(program['id'], kind='resource')
    return render_template('visit_criteria.html', program=program, criteria=CRITERIA,
                           criteria_url=CRITERIA_URL, documents=documents,
                           sources=core._source_catalog(core._continuous_improvement_story_for_manager()))


@bp.get('/improvement-timeline')
@role_required('coordinator')
def timeline():
    program = require_program()
    milestones = entries(program['id'], kind='milestone')
    milestones.sort(key=lambda e: (e['data'].get('event_date') or '9999', e['id']))
    return render_template('visit_timeline.html', program=program, cases=linked_cases(),
                           milestone_items=milestones, actions=scoped_actions(program['id']))


@bp.get('/campus-evidence')
@login_required
def campuses():
    program, filters, records = approved_context()
    protocols = [r for r in entries(program['id'], kind='resource')
                 if r['data'].get('document_kind') == 'campus_protocol'
                 and r['campus'] in {*filters['selected_campuses'],'Both','Program'}
                 and (not r['course_id'] or r['course_id'] in filters['selected_course_ids'])]
    return render_template('visit_campuses.html', program=program, coverage=campus_coverage(records),
                           matched=matched_campus_comparison(records), protocols=protocols,
                           filters=filters, is_manager=manager())


@bp.get('/capstone')
@login_required
def capstone():
    program, filters, records = approved_context()
    projects = entries(program['id'], kind='project')
    return render_template('visit_capstone.html', program=program, projects=projects,
                           courses=[c for c in filters['dimensions']['courses'] if c['code'] in ('MECE 4361','MECE 4362')],
                           is_manager=manager())


@bp.get('/evidence-workspace')
@role_required('coordinator')
def workspace():
    program = require_program()
    rows = entries(program['id'], published=False)
    if request.args.get('archived') == '1':
        rows = [decode_entry(row) for row in get_db().execute(
            "SELECT * FROM portal_entries WHERE program_id=? AND status='archived' ORDER BY id DESC",(program['id'],))]
    query = request.args.get('q','').strip()[:200].casefold()
    kind = request.args.get('kind','')
    rows = [r for r in rows if (not kind or r['kind'] == kind) and (not query or query in r['title'].casefold())]
    return render_template('visit_workspace.html', program=program, entries=rows, query=query, kind=kind)


def _text(form, name, *, required=False, limit=12000):
    value = str(form.get(name, '')).strip()
    if required and not value:
        raise ValueError(f"{name.replace('_',' ').capitalize()} is required.")
    if len(value) > limit:
        raise ValueError(f"{name.replace('_',' ').capitalize()} is too long.")
    return value


def _date(form, name):
    value = _text(form, name, limit=10)
    if value:
        date.fromisoformat(value)
    return value


def _reference(form, name, program_id, kind=None):
    raw = form.get(name)
    if not raw:
        return None
    ref = entry_by_id(int(raw), program_id, kind)
    if ref['status'] != 'published':
        raise ValueError('Publish the supporting document before linking it.')
    return ref['id']


def validate_entry(kind, form, program, previous):
    program_id = program['id']
    title = _text(form, 'title', required=True, limit=240)
    status = form.get('status','draft')
    if status not in ('draft','published','archived'):
        raise ValueError('Choose a valid publication state.')
    course_id = int(form['course_id']) if form.get('course_id') else None
    course = course_for_user(program_id, course_id) if course_id else None
    campus = form.get('campus', 'Program')
    if campus not in ('Edinburg','Brownsville','Both','Program') or bool(course_id) == (campus == 'Program'):
        raise ValueError('Course material needs a campus; program-wide material uses Program.')
    data = {'summary': _text(form, 'summary', required=True), 'period': _text(form,'period', limit=120),
            'event_date': _date(form,'event_date')}
    old_data = (previous or {}).get('data', {})
    file_upload = None
    if kind == 'resource':
        data['document_kind'] = form.get('document_kind','other')
        if data['document_kind'] not in RESOURCE_KINDS:
            raise ValueError('Choose a document category.')
        data['criteria'] = list(dict.fromkeys(form.getlist('criteria')))
        if any(c not in {c[0] for c in CRITERIA} for c in data['criteria']):
            raise ValueError('Invalid criterion.')
        data['version_label'] = _text(form,'version_label',required=True,limit=100)
        source_url = _text(form,'source_url',limit=2000)
        if source_url:
            parsed = urlparse(source_url)
            if parsed.scheme not in ('https','http') or not parsed.netloc or parsed.username or parsed.password:
                raise ValueError('Use a complete HTTP or HTTPS link without embedded credentials.')
        data['source_url'] = source_url
        for key in ('storage_key','original_filename','is_image'):
            data[key] = old_data.get(key)
        upload = request.files.get('file')
        if upload and upload.filename:
            original = secure_filename(upload.filename)
            suffix = Path(original).suffix.lower()
            if suffix not in core.ALLOWED_UPLOADS:
                raise ValueError('This file type is not supported.')
            is_image = suffix in ('.png','.jpg','.jpeg')
            if is_image:
                from PIL import Image
                try:
                    with Image.open(upload.stream) as image:
                        image.verify()
                except Exception as error:
                    raise ValueError('The uploaded image could not be verified.') from error
                finally:
                    upload.stream.seek(0)
            data.update(storage_key=f"{session['organization_id']}/{program_id}/portal/{secrets.token_hex(16)}{suffix}",
                        original_filename=original, is_image=is_image)
            file_upload = upload
        if not data.get('storage_key') and not source_url:
            raise ValueError('Attach a file or provide a source link.')
        if data['document_kind'] == 'photo' and not data.get('is_image'):
            raise ValueError('A project photograph needs an uploaded PNG or JPEG.')
        data['sharing_reviewed'] = form.get('sharing_reviewed') == 'yes'
        if status == 'published' and not data['sharing_reviewed']:
            raise ValueError('Confirm sharing permission and removal of student identifiers before publishing.')
    elif kind == 'plan':
        if not course or campus not in ('Edinburg','Brownsville'):
            raise ValueError('An assessment plan needs a course and a specific campus.')
        indicator_id = int(form.get('indicator_id','0'))
        indicator = get_db().execute('''SELECT pi.id,pi.code,pi.outcome_id,o.code AS outcome_code FROM performance_indicators pi
            JOIN outcomes o ON o.id=pi.outcome_id WHERE pi.id=? AND o.program_id=?''', (indicator_id,program_id)).fetchone()
        if not indicator:
            raise ValueError('Choose a performance indicator from this program.')
        data.update(dict(indicator))
        data['indicator_id'] = indicator_id
        data['owner'] = _text(form,'owner',required=True,limit=160)
        if not data['period']:
            raise ValueError('Enter the planned assessment period.')
    elif kind == 'milestone':
        data['stage'] = form.get('stage')
        if data['stage'] not in STAGES:
            raise ValueError('Choose a timeline stage.')
        data['case_slug'] = form.get('case_slug','')
        if data['case_slug'] and data['case_slug'] not in {c['slug'] for c in linked_cases()}:
            raise ValueError('Choose an existing improvement case.')
        data['resource_id'] = _reference(form,'resource_id',program_id,'resource')
        data['source_id'] = form.get('source_id','')
        if data['source_id'] and data['source_id'] not in SOURCE_FILES:
            raise ValueError('Unknown historical source.')
        data['record_id'] = int(form['record_id']) if form.get('record_id') else None
        if data['record_id']:
            rows = core._record_query(program_id, core._approved_where()+' AND ar.id=?', (data['record_id'],))
            if not rows or (course_id and rows[0]['course_id'] != course_id) or (campus in core.UTRGV_CAMPUSES and rows[0]['campus'] != campus):
                raise ValueError('Select an approved assessment in this course/campus scope.')
        data['due_on'] = _date(form,'due_on')
        data['completed'] = form.get('completed') == 'yes'
        if status == 'published' and (not (data['period'] or data['event_date']) or not any(data[k] for k in ('resource_id','record_id','source_id'))):
            raise ValueError('A published milestone needs its date/period and a supporting source.')
    elif kind == 'project':
        if not course or course['code'] not in ('MECE 4361','MECE 4362'):
            raise ValueError('Choose Senior Design I or II for a capstone project.')
        for field in ('problem','standards','constraints','decisions','testing','outcomes'):
            data[field] = _text(form,field,required=status == 'published')
        data['resource_id'] = _reference(form,'resource_id',program_id,'resource')
        data['photo_id'] = _reference(form,'photo_id',program_id,'resource')
        if data['photo_id']:
            photo = entry_by_id(data['photo_id'],program_id,'resource')
            if not photo['data'].get('is_image'):
                raise ValueError('Choose a verified uploaded image.')
        if status == 'published' and (not data['resource_id'] or not data['period']):
            raise ValueError('A published project needs its period and a supporting report or rubric.')
    # Never let a course-scoped entry link to another course/campus's document.
    for key in ('resource_id','photo_id'):
        if data.get(key):
            ref = entry_by_id(data[key],program_id,'resource')
            if ref['course_id'] != course_id or ref['campus'] not in (campus,'Both'):
                raise ValueError('Linked documents must belong to the same course and cover this campus.')
    if not manager():
        abort(403)
    return title, course_id, campus, status, data, file_upload


@bp.route('/evidence-workspace/new/<kind>', methods=['GET','POST'])
@bp.route('/evidence-workspace/<int:entry_id>/edit', methods=['GET','POST'])
@role_required('coordinator')
def edit(kind=None, entry_id=None):
    program = require_program(edit=request.method == 'POST')
    previous = entry_by_id(entry_id,program['id']) if entry_id else None
    kind = previous['kind'] if previous else kind
    if kind not in KINDS:
        abort(404)
    if request.method == 'POST':
        try:
            title, course_id, campus, status, payload, upload = validate_entry(kind,request.form,program,previous)
            db = get_db()
            revision = int(request.form.get('revision','0'))
            with db:
                if previous:
                    result = db.execute('''UPDATE portal_entries SET title=?,course_id=?,campus=?,status=?,payload_json=?,
                        revision=revision+1,updated_by=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND program_id=? AND revision=?''',
                        (title,course_id,campus,status,json.dumps(payload),g.user['id'],entry_id,program['id'],revision))
                    if result.rowcount != 1:
                        abort(409, 'This entry changed. Reload it before saving again.')
                else:
                    entry_id = db.execute('''INSERT INTO portal_entries(program_id,kind,course_id,campus,title,payload_json,status,created_by,updated_by)
                        VALUES(?,?,?,?,?,?,?,?,?)''',(program['id'],kind,course_id,campus,title,json.dumps(payload),status,g.user['id'],g.user['id'])).lastrowid
                if upload:
                    path = Path(current_app.config['UPLOAD_FOLDER']) / payload['storage_key']
                    path.parent.mkdir(parents=True,exist_ok=True)
                    upload.save(path)
                audit('update' if previous else 'create','portal_entry',entry_id,
                      {'kind':kind,'status':status,'previous_revision':previous['revision'] if previous else None})
            flash('Evidence entry saved. Published material appears in the linked pages.','success')
            return redirect(url_for('visit.workspace'))
        except (ValueError, TypeError) as error:
            flash(str(error),'error')
    dimensions = core._load_dimensions(program['id'])
    return render_template('visit_edit.html',program=program,kind=kind,entry=previous,
                           form=request.form if request.method == 'POST' else None,
                           dimensions=dimensions, resources=entries(program['id'],kind='resource'),
                           cases=linked_cases(), sources=core._source_catalog(core._continuous_improvement_story_for_manager()),
                           records=core._record_query(program['id'],core._approved_where()))


@bp.get('/evidence-workspace/<int:entry_id>')
@login_required
def detail(entry_id):
    program = require_program()
    entry = entry_by_id(entry_id,program['id'])
    references = {}
    for field in ('resource_id','photo_id'):
        if entry['data'].get(field):
            row = get_db().execute('SELECT * FROM portal_entries WHERE id=? AND program_id=?', (entry['data'][field],program['id'])).fetchone()
            if row and can_read(ref := decode_entry(row),program['id']) and ref['status']=='published':
                references[field] = ref
    return render_template('visit_detail.html',program=program,entry=entry,references=references,is_manager=manager())


@bp.get('/evidence-workspace/<int:entry_id>/file')
@login_required
def resource_file(entry_id):
    program = require_program()
    entry = entry_by_id(entry_id,program['id'],'resource')
    path = storage_path(entry['data'].get('storage_key',''))
    if not path:
        abort(404)
    image_inline = request.args.get('image') == '1' and entry['data'].get('is_image')
    return send_file(path,as_attachment=not image_inline,download_name=entry['data']['original_filename'])


@bp.get('/visit-readiness')
@role_required('coordinator')
def readiness():
    program = require_program()
    records = [dict(r) for r in core._record_query(program['id'],core._approved_where())]
    checks = readiness_checks(records,core._record_evidence(program['id'],[r['id'] for r in records]),
        entries(program['id'],published=False),scoped_actions(program['id']),
        core._source_catalog(core._continuous_improvement_story_for_manager()),storage_path)
    category = request.args.get('category','')
    categories = Counter(c['category'] for c in checks)
    if category:
        checks = [c for c in checks if c['category']==category]
    return render_template('visit_readiness.html',program=program,checks=checks,categories=categories,category=category)


def build_packet(program, records, selected_entries, attachments, *, title, course_id=None):
    """Immutable, escaped offline HTML + JSON + local files. Never copies the DB.

    Missing files are explicit manifest entries. External URLs remain links;
    they are never fetched and are not represented as frozen evidence.
    """
    output = io.BytesIO()
    files, omissions = [], []
    timestamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
    data = {'title':title,'program':program['name'],'created_at':timestamp,
            'scope':'Approved assessments; published supporting material. Equal assessment-measure weighting.',
            'course_id':course_id, 'records':[{key:r.get(key) for key in SAFE_RECORD_FIELDS} for r in records],
            'entries':[], 'attachments':[], 'sources':[], 'cases':[], 'files':files,'omissions':omissions}
    total_size = 0
    maximum = current_app.config.get('VISIT_PACKET_MAX_BYTES', 250 * 1024 * 1024)
    with ZipFile(output,'w',ZIP_DEFLATED) as archive:
        def add_file(path, name, label):
            nonlocal total_size
            if not path or not path.is_file():
                omissions.append({'title':label,'reason':'File missing from protected storage.'})
                return None
            if total_size + path.stat().st_size > maximum:
                abort(413,'Evidence packet is too large. Export individual course packets instead.')
            contents = path.read_bytes()
            total_size += len(contents)
            if total_size > maximum:
                abort(413,'Evidence packet is too large. Export individual course packets instead.')
            archive.writestr(name,contents)
            files.append({'path':name,'sha256':sha256(contents).hexdigest(),'bytes':len(contents)})
            return name
        for item in attachments:
            saved = {k:item.get(k) for k in ('id','assessment_id','title','description','source_url','created_at')}
            if item['storage_key']:
                name = f"artifacts/assessment-{item['id']}-{secure_filename(item['original_filename'] or 'document')}"
                saved['file'] = add_file(storage_path(item['storage_key']),name,item['title'])
            data['attachments'].append(saved)
        for item in selected_entries:
            saved = {k:item[k] for k in ('id','kind','title','course_id','campus','revision','status','updated_at')}
            payload = dict(item['data'])
            key = payload.pop('storage_key',None)
            if key:
                name = f"artifacts/resource-{item['id']}-{secure_filename(payload.get('original_filename') or 'document')}"
                payload['file'] = add_file(storage_path(key),name,item['title'])
            saved['data'] = payload
            data['entries'].append(saved)
        included_entries = {entry['id'] for entry in data['entries']}
        included_records = {record['id'] for record in records}
        for entry in data['entries']:
            for field in ('resource_id','photo_id'):
                reference = entry['data'].get(field)
                if reference and reference not in included_entries:
                    omissions.append({'title':entry['title'], 'reason':'Linked supporting entry is not published or not in this packet scope.'})
                    entry['data'][field] = None
            if entry['data'].get('record_id') and entry['data']['record_id'] not in included_records:
                omissions.append({'title':entry['title'], 'reason':'Linked assessment is not approved or not in this packet scope.'})
                entry['data']['record_id'] = None
        if manager():
            code = course_for_user(program['id'],course_id)['code'] if course_id else None
            cases = linked_cases(code)
            data['cases'] = cases
            documents = {s['document'] for case in cases for s in case['sources']} if course_id else set(SOURCE_FILES.values())
            for filename in sorted(documents):
                path = Path(current_app.root_path)/'source_documents'/filename
                data['sources'].append({'title':filename,'file':add_file(path, f'sources/{filename}',filename)})
        data['actions'] = scoped_actions(program['id'],course_id)
        # Preserve the published scope of a packet even when operational action
        # notes are linked to records which are currently unapproved.
        data['actions'] = [action for action in data['actions']
                           if not action['assessment_id'] or action['assessment_id'] in included_records]
        if manager() and course_id is None and current_app.config.get('EDITION')=='utrgv_mece':
            courses = get_db().execute('SELECT * FROM courses WHERE program_id=? ORDER BY code',(program['id'],)).fetchall()
            curriculum = curriculum_overview(courses,records,story=core._continuous_improvement_story_for_manager())
            data['curriculum'] = curriculum
            data['criteria'] = CRITERIA
            data['criteria_url'] = CRITERIA_URL
        data['charts'] = []
        if records:
            charts = core.generate_charts(records,chart_names=('course_attainment','semester_indicator'),
                dpi=150,export_caption=f'{title} | {timestamp} | Approved evidence | {len(records)} measures; equal weighting')
            for name,chart in charts.items():
                if chart.get('png_base64'):
                    chart_bytes = base64.b64decode(chart['png_base64'])
                    chart_path = f'figures/{name}.png'
                    archive.writestr(chart_path,chart_bytes)
                    files.append({'path':chart_path,'sha256':sha256(chart_bytes).hexdigest(),'bytes':len(chart_bytes)})
                    data['charts'].append({'title':chart.get('title',name.replace('_',' ').title()),'file':chart_path})
        data['external_link_note'] = 'External links are not frozen or automatically checked. Uploaded files are included when present.'
        archive.writestr('index.html',render_template('visit_packet.html',packet=data))
        archive.writestr('evidence.json',json.dumps(data,ensure_ascii=False,indent=2))
        archive.writestr('manifest.json',json.dumps({'created_at':timestamp,'files':files,'omissions':omissions},indent=2))
        # Hash the HTML and data too, not only the enclosed artifacts.
        hashes = '\n'.join(f'{sha256(archive.read(name)).hexdigest()}  {name}' for name in archive.namelist())
        archive.writestr('CHECKSUMS.sha256',hashes+'\n')
    return output.getvalue()


@bp.get('/courses/<int:course_id>/packet')
@login_required
def course_packet(course_id):
    program, filters, records = approved_context(course_id)
    course = course_for_user(program['id'],course_id)
    material = entries(program['id'],course_id=course_id)
    selected = set(filters['selected_campuses'])
    if selected:
        material = [e for e in material if e['campus'] in selected or e['campus']=='Both']
    payload = build_packet(program,records,material,core._record_evidence(program['id'],[r['id'] for r in records]),
                           title=f"{course['code']} evidence packet",course_id=course_id)
    return send_file(io.BytesIO(payload),as_attachment=True,download_name=f"{course['code'].replace(' ','-')}-evidence.zip",mimetype='application/zip')


@bp.route('/visit-editions',methods=['GET','POST'])
@role_required('coordinator')
def editions():
    program = require_program(edit=request.method=='POST')
    db = get_db()
    if request.method == 'POST':
        try:
            title = _text(request.form,'title',limit=160)
        except ValueError as error:
            abort(400,str(error))
        if not title or request.form.get('sharing_reviewed') != 'yes':
            flash('Provide an edition title and confirm the evidence-sharing review.','error')
        else:
            # All metadata reads use one SQLite read transaction; publication
            # and faculty changes after this snapshot do not rewrite its files.
            db.execute('BEGIN')
            try:
                records = [dict(r) for r in core._record_query(program['id'],core._approved_where())]
                payload = build_packet(program,records,entries(program['id']),
                    core._record_evidence(program['id'],[r['id'] for r in records]),title=title)
            finally:
                db.rollback()
            key = f"{session['organization_id']}/{program['id']}/visit-editions/{secrets.token_hex(20)}.zip"
            path = Path(current_app.config['UPLOAD_FOLDER'])/key
            path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('xb') as stream:
                stream.write(payload)
            with db:
                edition_id = db.execute('''INSERT INTO portal_visit_editions(program_id,title,storage_key,sha256,record_count,created_by)
                    VALUES(?,?,?,?,?,?)''',(program['id'],title,key,sha256(payload).hexdigest(),len(records),g.user['id'])).lastrowid
                audit('create','visit_edition',edition_id,{'record_count':len(records),'sha256':sha256(payload).hexdigest()})
            flash('Visit edition saved. Future edits will not change this edition.','success')
            return redirect(url_for('visit.editions'))
    rows = db.execute('SELECT * FROM portal_visit_editions WHERE program_id=? ORDER BY id DESC',(program['id'],)).fetchall()
    return render_template('visit_editions.html',program=program,editions=rows)


@bp.get('/visit-editions/<int:edition_id>/download')
@role_required('coordinator')
def edition_download(edition_id):
    program = require_program()
    row = get_db().execute('SELECT * FROM portal_visit_editions WHERE id=? AND program_id=?',(edition_id,program['id'])).fetchone()
    path = storage_path(row['storage_key']) if row else None
    if not path:
        abort(404)
    if sha256(path.read_bytes()).hexdigest() != row['sha256']:
        abort(409,'This saved edition failed its integrity check. Restore a verified backup.')
    return send_file(path,as_attachment=True,download_name=f'UTRGV-visit-edition-{edition_id}.zip')
