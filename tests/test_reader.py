import http.cookiejar
import io
from email.message import Message
import urllib.error
from pathlib import Path
import unittest
from unittest.mock import Mock
from urllib.request import Request
from study_reader.managebac import (parse_tasks, parse_grades, parse_classes, due_date,
    merge_tasks, ManageBacReader, ReaderError, safe_url, TASKS, CLASSES, ORIGIN)
from study_reader.transport import ReadOnlyTransport, NoRedirect
from study_reader.timetable import UnconfiguredTimetableProvider

FIXTURES = Path(__file__).parent / 'fixtures'
TASK_HTML = (FIXTURES / 'tasks.html').read_text()
GRADE_HTML = (FIXTURES / 'grades.html').read_text()
EMPTY = '<div class="js-tasks"></div>'


class FakeTransport:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def get(self, url):
        self.calls.append(url)
        value = self.pages[url]
        if isinstance(value, Exception):
            raise value
        return value


class ReaderTests(unittest.TestCase):
    def test_multiline_tasks_date_and_entity(self):
        tasks, following, errors = parse_tasks(TASK_HTML, timezone_name="Asia/Shanghai")
        self.assertEqual(len(tasks), 2)
        self.assertEqual(tasks[0]['title'], 'Synthetic & Task')
        self.assertEqual(tasks[0]['due']['value'], '2026-10-24T13:30:00+08:00')
        self.assertEqual(tasks[0]['score_raw'], '6')
        self.assertIsNone(tasks[1]['due']['value'])
        self.assertEqual(tasks[1]['due']['raw'], 'Oct 24')
        self.assertFalse(errors)
        self.assertIsNone(following)

    def test_missing_dates_are_retained(self):
        html = '<div class="js-tasks"><div class="f-task-tile"><a class="f-tile__title-link" href="/student/classes/1/core_tasks/2">No date</a></div></div>'
        rows, _, _ = parse_tasks(html)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['due'], {'raw': None, 'value': None, 'precision': 'unknown'})

    def test_no_year_or_invalid_date_is_not_guessed(self):
        for raw in ('Dec 31, 1:00 PM', 'Feb 30, 2026, 1:00 PM', 'Oct 24, 2026'):
            self.assertIsNone(due_date(raw)['value'])

    def test_grades_official_and_no_boundaries(self):
        grades = parse_grades(GRADE_HTML, '12', 'Maths', ORIGIN + '/student/classes/12/core_tasks')
        self.assertEqual(grades['overall']['percentage'], 80)
        self.assertFalse(grades['overall']['estimated'])
        self.assertIsNone(grades['categories'][1]['weight_percent'])
        self.assertIsNone(grades['categories'][1]['percentage'])
        self.assertIsNone(grades['grade_boundaries'])
        self.assertIsNone(grades['estimated_grade'])

    def test_unknown_layout_not_empty_success(self):
        for parse in (parse_tasks, parse_classes):
            with self.assertRaises(ReaderError):
                parse('<html>changed</html>')
        with self.assertRaises(ReaderError):
            parse_grades('<div class="sidebar-items-list"></div>', '1', '', '')

    def test_login_detection(self):
        for html in ('<input name="password">', '<title>ManageBac | Login</title>'):
            with self.assertRaisesRegex(ReaderError, 'authentication_required'):
                parse_tasks(html)

    def test_duplicate_update_replaces_score_and_null(self):
        rows, _, _ = parse_tasks(TASK_HTML)
        updated = dict(rows[0], score_raw='7', status='Assessed', views=['past'])
        removed = dict(updated, score_raw=None, views=['overdue'])
        merged, warnings = merge_tasks([rows[0], updated, removed])
        self.assertEqual(len(merged), 1)
        self.assertIsNone(merged[0]['score_raw'])
        self.assertEqual(merged[0]['views'], ['overdue', 'past', 'upcoming'])
        self.assertEqual(len(warnings), 2)

    def test_class_ids_not_names_are_keys(self):
        self.assertEqual(parse_classes('<a href="/student/classes/1">Maths</a><a href="/student/classes/2">Maths</a>'), {'1': 'Maths', '2': 'Maths'})

    def test_allowlist(self):
        for url in (TASKS, TASKS + '?view=past&page=2', CLASSES, ORIGIN + '/student/classes/2/core_tasks'):
            self.assertTrue(safe_url(url), url)
        for url in ('http://sdgj.managebac.cn/student/classes/my',
                    'https://evil.test/student/classes/my', ORIGIN + '/logout',
                    ORIGIN + '/student/classes/my?delete=1', TASKS + '?view=upcoming&view=past',
                    'https://user@sdgj.managebac.cn/student/classes/my',
                    ORIGIN + ':444/student/classes/my', TASKS + '#fragment'):
            self.assertFalse(safe_url(url), url)

    def test_redirects_blocked_before_cookies_leave(self):
        for target in ('https://evil.test/', ORIGIN + '/login', TASKS):
            with self.assertRaises(ReaderError):
                NoRedirect().redirect_request(Request(TASKS), None, 302, '', {}, target)

    def test_transport_rejects_without_request(self):
        t = ReadOnlyTransport(http.cookiejar.CookieJar())
        t._opener = Mock()
        with self.assertRaises(ReaderError):
            t.get('https://evil.test/')
        t._opener.open.assert_not_called()
        self.assertFalse(hasattr(t, 'post'))

    def test_partial_failure_preserves_successes(self):
        next_url = TASKS + '?view=upcoming&page=2'
        t = FakeTransport({TASKS + '?view=upcoming': TASK_HTML + '<a class="next" href="' + next_url + '">next</a>',
                           next_url: ReaderError('network_error'),
                           TASKS + '?view=past': EMPTY, TASKS + '?view=overdue': EMPTY})
        result = ManageBacReader(t).read(include_grades=False)
        self.assertFalse(result['complete'])
        self.assertEqual(len(result['tasks']), 2)
        self.assertEqual(result['errors'][0]['code'], 'network_error')
        self.assertFalse(result['pagination']['upcoming']['complete'])
        self.assertTrue(result['pagination']['past']['complete'])

    def test_limits_cycles_and_bad_pagination(self):
        for href, limit, expected in ((TASKS + '?view=upcoming&page=2', 1, 'pagination_limit'),
                                      (TASKS + '?view=upcoming', 5, 'pagination_cycle')):
            t = FakeTransport({TASKS + '?view=upcoming': EMPTY + '<a class="next" href="' + href + '">next</a>',
                               TASKS + '?view=past': EMPTY, TASKS + '?view=overdue': EMPTY})
            self.assertEqual(ManageBacReader(t, limit).read(False)['errors'][0]['code'], expected)
        for href in ('https://evil.test/tasks_and_deadlines', TASKS + '?view=past&page=2'):
            with self.assertRaises(ReaderError):
                parse_tasks(EMPTY + '<a class="next" href="' + href + '">next</a>')

    def test_full_read(self):
        t = FakeTransport({TASKS + '?view=' + v: EMPTY for v in ('upcoming', 'past', 'overdue')})
        t.pages[CLASSES] = '<a href="/student/classes/12">Maths</a>'
        t.pages[ORIGIN + '/student/classes/12/core_tasks'] = GRADE_HTML
        result = ManageBacReader(t).read()
        self.assertTrue(result['complete'])
        self.assertEqual(len(result['grades']), 1)

    def test_relative_pagination_and_missing_view(self):
        rows, following, _ = parse_tasks(EMPTY + '<a rel="next" href="?view=upcoming&amp;page=2">Next</a>', TASKS + '?view=upcoming')
        self.assertEqual(following, TASKS + '?view=upcoming&page=2')
        with self.assertRaisesRegex(ReaderError, 'pagination_view_missing'):
            parse_tasks(EMPTY + '<a rel="next" href="?page=2">Next</a>', TASKS + '?view=past', view='past')
        with self.assertRaisesRegex(ReaderError, 'missing_pagination_url'):
            parse_tasks(EMPTY + '<a rel="next">Next</a>')

    def test_malformed_urls_are_safe_errors(self):
        bad = 'https://[bad/student/classes/1/core_tasks/2'
        rows, _, errors = parse_tasks('<div class="js-tasks"><div class="f-task-tile"><a class="f-tile__title-link" href="' + bad + '">Test</a></div></div>')
        self.assertEqual(rows, [])
        self.assertEqual(errors[0]['code'], 'invalid_task_identity')
        with self.assertRaisesRegex(ReaderError, 'invalid_class_url'):
            parse_classes('<a href="' + bad + '">Class</a>')
        with self.assertRaisesRegex(ReaderError, 'unsafe_pagination_url'):
            parse_tasks(EMPTY + '<a rel="next" href="' + bad + '">Next</a>')

    def test_offline_provenance_has_no_fetch_time(self):
        rows, _, _ = parse_tasks(TASK_HTML, mode='offline')
        self.assertIsNone(rows[0]['provenance']['fetched_at'])
        self.assertEqual(rows[0]['provenance']['freshness'], 'offline_unknown')

    def test_transport_response_guards_and_safe_errors(self):
        t = ReadOnlyTransport(http.cookiejar.CookieJar(), max_bytes=20)
        def response(body=b'<html></html>', content_type='text/html', charset='utf-8', url=TASKS):
            r = Mock()
            r.__enter__ = Mock(return_value=r)
            r.__exit__ = Mock(return_value=False)
            r.geturl.return_value = url
            r.status = 200
            r.headers = Message()
            r.headers['Content-Type'] = content_type + '; charset=' + charset
            r.read.return_value = body
            t._opener = Mock()
            t._opener.open.return_value = r
            return r
        response()
        self.assertEqual(t.get(TASKS), '<html></html>')
        self.assertEqual(t._opener.open.call_args[0][0].method, 'GET')
        for kwargs, code in (({'body': b'x' * 21}, 'response_too_large'),
                             ({'content_type': 'application/json'}, 'unexpected_content_type'),
                             ({'charset': 'not-a-charset'}, 'invalid_response_encoding'),
                             ({'url': 'https://evil.test/'}, 'unexpected_response_url')):
            response(**kwargs)
            with self.assertRaisesRegex(ReaderError, code):
                t.get(TASKS)
        for exc, code in ((urllib.error.HTTPError(TASKS, 401, 'SECRET', {}, io.BytesIO()), 'authentication_required'),
                          (urllib.error.URLError('SECRET'), 'network_error')):
            t._opener.open.side_effect = exc
            with self.assertRaisesRegex(ReaderError, '^' + code + '$'):
                t.get(TASKS)

    def test_assessed_pending_is_not_submission_inference(self):
        html = TASK_HTML.replace('<div class="f-tile__suffix">',
            '<div class="labels-set"><span class="badge color-box-gray"><span class="badge-label">Pending</span></span></div><div class="f-tile__suffix">')
        rows, _, _ = parse_tasks(html)
        self.assertEqual(rows[0]['assessment_status'], 'Assessed')
        self.assertEqual(rows[0]['badge_labels_raw'], ['Pending'])
        self.assertIsNone(rows[0]['submission_status'])
        self.assertIsNone(rows[1]['assessment_status'])

    def test_due_score_area_not_an_assessment_or_submission_status(self):
        html = TASK_HTML.replace('f-task-score--assessment', 'f-task-score--due')
        rows, _, _ = parse_tasks(html)
        self.assertIsNone(rows[0]['assessment_status'])
        self.assertIsNone(rows[0]['submission_status'])
        html = TASK_HTML.replace('f-task-score--assessment', 'f-task-score--not-assessed')
        rows, _, _ = parse_tasks(html)
        self.assertEqual(rows[0]['assessment_status'], 'Not Assessed')
        self.assertIsNone(rows[0]['submission_status'])

    def test_timezone_required_and_never_infers_missing_year(self):
        raw = 'Oct 24, 2026, 1:30 PM'
        self.assertIsNone(due_date(raw)['value'])
        self.assertEqual(due_date(raw)['resolution'], 'timezone_required')
        self.assertEqual(due_date(raw, timezone_name='Asia/Shanghai')['value'], '2026-10-24T13:30:00+08:00')
        self.assertEqual(due_date(raw, timezone_name='UTC')['value'], '2026-10-24T13:30:00+00:00')
        self.assertIsNone(due_date('Jan 1, 1:30 PM', timezone_name='Asia/Shanghai')['value'])
        with self.assertRaisesRegex(ReaderError, 'invalid_timezone_configuration'):
            parse_tasks(TASK_HTML, timezone_name='Invalid/Timezone')

    def test_dst_ambiguity_and_gap_are_not_guessed(self):
        for raw, reason in (('Nov 1, 2026, 1:30 AM', 'ambiguous_local_time'),
                            ('Mar 8, 2026, 2:30 AM', 'nonexistent_local_time')):
            due = due_date(raw, timezone_name='America/New_York')
            self.assertIsNone(due['value'])
            self.assertEqual(due['resolution'], reason)

    def test_reader_passes_explicit_timezone(self):
        t = FakeTransport({TASKS + '?view=' + v: TASK_HTML if v == 'upcoming' else EMPTY
                           for v in ('upcoming', 'past', 'overdue')})
        result = ManageBacReader(t, timezone_name='Asia/Shanghai').read(False)
        self.assertTrue(result['complete'])
        self.assertEqual(result['tasks'][0]['due']['timezone_source'], 'caller_supplied')

    def test_timetable_never_claims_fetched(self):
        result = UnconfiguredTimetableProvider().read()
        self.assertFalse(result['complete'])
        self.assertIsNone(result['fetched_at'])
        self.assertEqual(result['freshness'], 'not_fetched')


if __name__ == '__main__':
    unittest.main()
