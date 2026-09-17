"""Evidence-first UI, export precision, and authorization regression tests."""
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from html.parser import HTMLParser

import test_analytics_filters as filter_fixtures
import test_faculty_course_isolation as scope_fixtures
from test_analytics_filters import captured_templates
from abet_platform.db import get_db
from abet_platform.presentation import evidence_overview, matched_campus_comparison, paginate_records, VIEW_CHARTS
import abet_platform.routes as routes


class PresentationModelTests(unittest.TestCase):
    def record(self, **updates):
        record = dict(id=1, status='approved', course_id=1, course_label='MECE 3320', course_code='MECE 3320',
                      term_id=1, term_label='Spring 2025', term_order=1, outcome_id=1,
                      outcome_code='SLO1', outcome_label='SLO1: Test', indicator_id=1,
                      indicator_code='PI-1', indicator_label='PI-1: Test', method='direct',
                      bloom_level='Apply', rubric_id=1, assessment_tool='Exam 1',
                      campus='Edinburg', target=70., attainment=80., observations='', action_notes='')
        record.update(updates)
        return record

    def test_no_evidence_is_not_zero_and_mean_threshold_uses_unrounded_values(self):
        outcomes = [dict(id=1, code='SLO1', description='Test'), dict(id=2, code='SLO2', description='No evidence')]
        result = evidence_overview([self.record(attainment=69.96)], outcomes)
        self.assertEqual(result['means_met'], 0)
        self.assertEqual(result['cards'][0]['mean'], 70.)
        self.assertFalse(result['cards'][0]['mean_met'])
        self.assertIsNone(result['cards'][1]['mean'])
        self.assertEqual(result['cards'][1]['status'], 'No evidence')

    def test_preview_is_not_mislabeled_approved(self):
        result = evidence_overview([self.record(status='draft')], [], approved_only=False)
        self.assertEqual(result['count'], 1)
        self.assertIn('selected', result['takeaway'])
        self.assertNotIn('approved', result['takeaway'])

    def test_campus_matching_rejects_different_terms_tools_and_indicators(self):
        rows = [self.record(), self.record(campus='Brownsville', attainment=90),
                self.record(campus='Brownsville', attainment=10, term_id=2),
                self.record(campus='Brownsville', attainment=20, assessment_tool='Final'),
                self.record(campus='Brownsville', attainment=30, indicator_id=2)]
        result = matched_campus_comparison(rows)
        self.assertEqual(result['count'], 1)
        self.assertEqual(result['difference'], 10)
        self.assertEqual(result['brownsville'], 90)

    def test_matched_cells_have_equal_weight_not_unequal_course_counts(self):
        rows = [self.record(attainment=80)] * 8 + [self.record(campus='Brownsville', attainment=90)]
        rows += [self.record(course_id=2, attainment=50), self.record(course_id=2, campus='Brownsville', attainment=50)]
        result = matched_campus_comparison(rows)
        self.assertEqual(result['count'], 2)
        self.assertEqual(result['edinburg'], 65)
        self.assertEqual(result['brownsville'], 70)

    def test_record_search_is_paged_and_does_not_mutate_records(self):
        rows = [self.record(id=i) for i in range(45)]
        result = paginate_records(rows, '3320', 2)
        self.assertEqual(len(result['items']), 20)
        self.assertEqual(result['first'], 21)
        self.assertEqual(result['last'], 40)
        self.assertEqual(result['pages'], 3)
        self.assertEqual(len(rows), 45)


class RedesignRouteTests(unittest.TestCase):
    def setUp(self):
        self.fixture = filter_fixtures.AnalyticsFilterTests()
        self.fixture.setUp()
        self.app, self.client, self.ids = self.fixture.app, self.fixture.client, self.fixture.ids

    def tearDown(self):
        self.fixture.tearDown()

    def test_all_tabs_render_and_only_generate_their_own_charts(self):
        for view, names in VIEW_CHARTS.items():
            with self.subTest(view=view), captured_templates(self.app) as captured:
                response = self.client.get('/analytics', query_string={'view': view})
                self.assertEqual(response.status_code, 200)
                expected = set(names) - {'campus_comparison'}  # Generic edition
                self.assertEqual(set(captured[-1][1]['charts']), expected)
        self.assertEqual(self.client.get('/analytics?view=unknown').status_code, 400)

    def test_filter_links_preserve_repeated_courses_and_preview_state(self):
        query = [('course_id', self.ids['courses']['ME 101']), ('course_id', self.ids['courses']['ME 303']),
                 ('evidence_scope', 'all'), ('view', 'courses')]
        response = self.client.get('/analytics', query_string=query)
        class Links(HTMLParser):
            def __init__(self): super().__init__(); self.links=[]
            def handle_starttag(self,tag,attrs):
                if tag=='a': self.links.append(dict(attrs).get('href',''))
        links=Links(); links.feed(response.text)
        download=next(link for link in links.links if '/charts/course_attainment/download' in link and 'format=svg' in link)
        args=parse_qs(urlparse(download).query)
        self.assertEqual(set(args['course_id']), {str(self.ids['courses']['ME 101']), str(self.ids['courses']['ME 303'])})
        self.assertEqual(args['evidence_scope'], ['all'])

    def test_exports_are_valid_and_source_values_are_not_changed(self):
        for fmt, prefix, mime in [('png', b'\x89PNG', 'image/png'), ('svg', b'<?xml', 'image/svg+xml'), ('pdf', b'%PDF', 'application/pdf')]:
            response = self.client.get('/analytics/charts/course_attainment/download', query_string={'format':fmt})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.data.startswith(prefix))
            self.assertIn(mime, response.content_type)
            self.assertIn('attachment', response.headers['Content-Disposition'])
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(self.client.get('/analytics/charts/not-a-chart/download').status_code, 404)
        self.assertEqual(self.client.get('/analytics/charts/trend_line/download?format=html').status_code, 400)

    def test_cache_reuses_unchanged_scope_and_invalidates_when_result_changes(self):
        with patch.object(routes, 'generate_charts', wraps=routes.generate_charts) as renderer:
            self.client.get('/analytics')
            self.client.get('/analytics')
            self.assertEqual(renderer.call_count, 1)
            with self.app.app_context():
                db=get_db()
                db.execute('UPDATE assessment_records SET target=99 WHERE id=?', (self.ids['records']['approved_a'],))
                db.commit()
            self.client.get('/analytics')
            self.assertEqual(renderer.call_count, 2)

    def test_evaluator_and_report_reject_unapproved_scope(self):
        for route in ('/review','/report','/evidence-library'):
            self.assertEqual(self.client.get(route+'?evidence_scope=all').status_code, 400)
        draft=self.ids['records']['draft_a']
        self.assertEqual(self.client.get(f'/review/records/{draft}').status_code,404)

    def test_evaluator_report_and_library_keep_the_selected_course(self):
        for route in ('/review', '/report', '/evidence-library'):
            with self.subTest(route=route), captured_templates(self.app) as captured:
                response = self.client.get(route, query_string={'course_id': self.ids['courses']['ME 101']})
                self.assertEqual(response.status_code, 200)
                context = captured[-1][1]
                self.assertEqual(context['overview']['count'], 1)
                self.assertEqual(context['selection_labels'], ['Courses: ME 101'])

    def test_export_carries_approval_state_and_selection_inside_the_figure(self):
        response = self.client.get('/analytics/charts/course_attainment/download', query_string={
            'format': 'svg', 'evidence_scope': 'all', 'course_id': self.ids['courses']['ME 101']})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'PREVIEW', response.data)
        self.assertIn(b'UNAPPROVED EVIDENCE', response.data)
        self.assertIn(b'ME 101', response.data)
        self.assertNotIn(b'ME 303', response.data)

    def test_filtered_outcome_does_not_label_unselected_outcomes_as_missing(self):
        with self.app.app_context():
            outcome_id = get_db().execute('SELECT outcome_id FROM assessment_records WHERE id=?',
                                         (self.ids['records']['approved_a'],)).fetchone()[0]
        for route in ('/review', '/report'):
            with self.subTest(route=route), captured_templates(self.app) as captured:
                response = self.client.get(route, query_string={'outcome_id': outcome_id})
                self.assertEqual(response.status_code, 200)
                self.assertEqual([card['id'] for card in captured[-1][1]['overview']['cards']], [outcome_id])

    def test_neutral_titles_preserve_detailed_results(self):
        with self.app.app_context():
            db = get_db()
            db.execute('UPDATE assessment_records SET target=99 WHERE status=?', ('approved',))
            db.commit()
        for route in ('/', '/review', '/analytics', '/report'):
            with self.subTest(route=route), captured_templates(self.app) as captured:
                response = self.client.get(route)
                self.assertEqual(response.status_code, 200)
                self.assertIn(b'Assessment summary', response.data)
                self.assertNotIn(b'measures are below their configured targets', response.data)
                self.assertNotIn(b'Review the individual indicators before drawing', response.data)
                overview = captured[-1][1]['overview']
                self.assertEqual(overview['below_count'], 2)
                self.assertEqual(sum(card['below'] for card in overview['cards']), 2)
                if route == '/review':
                    self.assertIn(b'<h1>Criterion 4 overview</h1>', response.data)
                    self.assertNotIn(b'From student learning', response.data)
                    self.assertNotIn(b'direct measures and', response.data)
                    for title in ('Student outcomes', 'Continuous improvement', 'Campus comparison', 'Supporting evidence'):
                        self.assertIn(f'<h2>{title}</h2>', response.text)


class RedesignScopeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = scope_fixtures.FacultyCourseIsolationTests()
        self.fixture.setUp()
        self.app, self.client, self.ids = self.fixture.app, self.fixture.client, self.fixture.ids
        self.fixture.as_user(self.ids['faculty_a'])

    def tearDown(self): self.fixture.tearDown()

    def test_new_views_never_include_another_course_or_global_story(self):
        for path in ('/review','/evidence-library','/analytics?view=records','/analytics?view=campus'):
            response=self.client.get(path)
            self.assertEqual(response.status_code,200,path)
            self.assertNotIn(b'MECE 2340', response.data)
            self.assertNotIn(b'B_SECRET', response.data)
            self.assertNotIn(b'PROGRAMWIDE_SECRET',response.data)
            self.assertNotIn(b'68% \xe2\x86\x92 74%', response.data)
        self.assertEqual(self.client.get('/review/sources/submitted').status_code,403)
        self.assertEqual(self.client.get('/review/cases/slo6-mece3320-verified-loop').status_code,403)

    def test_export_and_readonly_record_routes_recheck_access(self):
        with self.app.app_context():
            db=get_db()
            other_record=db.execute('SELECT id FROM assessment_records WHERE course_id=? LIMIT 1',(self.fixture.course_b,)).fetchone()[0]
        self.assertEqual(self.client.get(f'/review/records/{other_record}').status_code,404)
        for route in ('/review','/report','/evidence-library','/analytics/charts/course_attainment/download'):
            response=self.client.get(route,query_string={'course_id':self.fixture.course_b})
            self.assertEqual(response.status_code,403,route)

    def test_permission_revocation_cannot_reuse_cached_chart(self):
        first=self.client.get('/analytics/charts/course_attainment/download')
        self.assertEqual(first.status_code,200)
        with self.app.app_context():
            db=get_db(); db.execute('DELETE FROM course_campus_assignments WHERE user_id=?',(self.ids['faculty_a'],)); db.commit()
        self.assertEqual(self.client.get('/analytics/charts/course_attainment/download').status_code,404)

    def test_owner_can_retrieve_protected_documents_without_mutating_database(self):
        self.fixture.as_user(self.ids['owner'])
        with self.app.app_context(): before=get_db().execute('SELECT COUNT(*) FROM audit_events').fetchone()[0]
        for path in ('/review','/review/cases/slo6-mece3320-verified-loop','/evidence-library','/review/sources/slo2'):
            response=self.client.get(path)
            self.assertEqual(response.status_code,200,path)
            response.close()
        with self.app.app_context(): after=get_db().execute('SELECT COUNT(*) FROM audit_events').fetchone()[0]
        self.assertEqual(before,after)


if __name__ == '__main__': unittest.main()
