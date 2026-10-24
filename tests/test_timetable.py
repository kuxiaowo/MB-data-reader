from pathlib import Path
import unittest
from study_reader.timetable import parse_timetable, OfflineTimetableProvider

HTML = (Path(__file__).parent / 'fixtures/timetable.html').read_text()


class TimetableTests(unittest.TestCase):
    def test_seven_days_rollover_and_today_marker(self):
        result = parse_timetable(HTML)
        self.assertEqual(result['errors'], [])
        self.assertEqual(len(result['lessons']), 7)
        self.assertEqual(result['lessons'][0]['date'], '2026-12-28')
        self.assertEqual(result['lessons'][6]['date'], '2027-01-03')
        self.assertEqual(result['days'][2]['day_label_raw'], '今')
        self.assertEqual(result['lessons'][2]['date'], '2026-12-30')
        self.assertIsNone(result['fetched_at'])
        self.assertFalse(result['complete'])
        self.assertEqual(result['lessons'][0]['start_time'], '08:00')

    def test_exception_is_date_specific_not_recurring(self):
        result = parse_timetable(HTML)
        self.assertEqual(result['exceptions'], [{'date': '2026-12-30', 'text': 'Synthetic one-day change', 'recurring': False}])
        self.assertEqual(result['lessons'][2]['exceptions'], ['Synthetic one-day change'])
        self.assertTrue(all(not row['recurring'] for row in result['lessons']))

    def test_explicit_range_provider_and_missing_context(self):
        html = HTML.replace('2026-12-28 - 2027-01-03', '12月28日 - 01月03日')
        self.assertEqual(parse_timetable(html)['errors'][0]['code'], 'explicit_week_start_required')
        result = OfflineTimetableProvider(html, week_start='2026-12-28', week_end='2027-01-03').read()
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['date_context_source'], 'caller_supplied')

    def test_short_displayed_range_must_match_explicit_context(self):
        html = HTML.replace('2026-12-28 - 2027-01-03', '12月28日 - 01月03日')
        result = parse_timetable(html, week_start='2027-01-04')
        self.assertEqual(result['errors'][0]['code'], 'date_context_mismatch')
        self.assertFalse(result['lessons'])

    def test_contradictory_year_or_numeric_day_is_rejected(self):
        short = HTML.replace('2026-12-28 - 2027-01-03', '12月28日 - 01月03日')
        result = parse_timetable(short, week_start='2027-12-28')
        self.assertEqual(result['errors'][0]['code'], 'displayed_year_context_mismatch')
        self.assertEqual(result['lessons'], [])
        result = parse_timetable(HTML.replace('<div class="cell-day">28</div>', '<div class="cell-day">1</div>', 1))
        self.assertEqual(result['errors'][0]['code'], 'day_label_context_mismatch')
        self.assertEqual(result['lessons'], [])
        # At rollover either boundary year may be displayed; it is not an inference anchor.
        result = parse_timetable(HTML.replace('<span>2026</span>', '<span>2027年</span>'))
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['lessons'][0]['date'], '2026-12-28')

    def test_blank_week_not_free(self):
        html = '<div class="schedule-card">' + '<div class="y-ui__weekly-calendar__cell"></div>' * 7 + '</div>'
        result = parse_timetable(html, week_start='2027-01-04')
        self.assertEqual(result['data_status'], 'data_unavailable')
        self.assertFalse(result['complete'])
        self.assertTrue(all(day['data_status'] == 'unknown' for day in result['days']))
        self.assertEqual(result['errors'][0]['code'], 'no_lessons_observed_not_proven_free')

    def test_invalid_or_mismatched_range(self):
        for kwargs, code in (({'week_start': 'no'}, 'invalid_date_context'),
                             ({'week_start': '2026-12-28', 'week_end': '2027-01-04'}, 'date_range_must_span_seven_days'),
                             ({'week_start': '2027-01-04'}, 'date_context_mismatch')):
            result = parse_timetable(HTML, **kwargs)
            self.assertEqual(result['errors'][0]['code'], code)
            self.assertEqual(result['lessons'], [])

    def test_missing_and_invalid_times_retain_lessons(self):
        for raw in ('', '25:00 - 26:00', '09:00 - 08:00'):
            result = parse_timetable(HTML.replace('08:00 - 08:45', raw))
            self.assertEqual(len(result['lessons']), 7)
            self.assertTrue(all(row['start_time'] is None for row in result['lessons']))
            self.assertTrue(all(err['code'] == 'missing_or_unrecognized_lesson_time' for err in result['errors']))

    def test_exact_field_selectors_and_misleading_period_label(self):
        result = parse_timetable(HTML.replace('08:00 - 08:45', '上午 14:00 - 14:45'))
        row = result['lessons'][0]
        self.assertEqual(row['start_time'], '14:00')
        self.assertEqual(row['course_name'], 'Synthetic course 0')
        self.assertEqual(row['class_name'], 'Example class')
        self.assertEqual(row['room'], 'Example room')
        self.assertEqual(row['teacher'], 'Example teacher')
        self.assertFalse(result['errors'])

    def test_overlapping_entries_are_preserved(self):
        extra = '<div class="content-item"><span class="content-item__time">上午 08:10-08:30</span><div class="content-item__course-name">Synthetic overlapping reminder</div><span class="el-alert__title">Synthetic reminder; verify separate notice</span></div>'
        html = HTML.replace('<div class="content-item">', extra + '<div class="content-item">', 1)
        result = parse_timetable(html)
        self.assertEqual(len(result['lessons']), 8)
        self.assertEqual(result['days'][0]['lesson_count'], 2)
        self.assertEqual(result['lessons'][0]['date'], result['lessons'][1]['date'])
        self.assertFalse(result['errors'])

    def test_error_alert_and_unknown_layout(self):
        self.assertEqual(parse_timetable('<html>Login</html>')['errors'][0]['code'], 'unrecognized_or_ambiguous_timetable_markup')
        result = parse_timetable(HTML.replace('<div class="schedule-card">', '<div class="schedule-card"><span class="el-alert__title">Synthetic error</span>'))
        self.assertIn({'date': None, 'text': 'Synthetic error', 'recurring': False}, result['exceptions'])
        self.assertTrue(any(e['code'] == 'unscoped_timetable_alert' for e in result['errors']))
        self.assertEqual(parse_timetable(HTML.replace('y-ui__weekly-calendar__cell', 'changed', 1))['errors'][0]['code'], 'expected_seven_day_columns')


if __name__ == '__main__':
    unittest.main()
