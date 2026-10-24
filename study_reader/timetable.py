"""Read-only timetable providers; offline rendered DOM, never credentials/API guesses."""
import re
from datetime import date, timedelta
from typing import Protocol
from .html import Tree, Node, txt
from .managebac import now

HOME = 'https://student.hyqzedu.com/app-base-info/app/home'


class TimetableProvider(Protocol):
    def read(self) -> dict:
        """Return source, fetched_at, freshness, complete, lessons and errors."""
        ...


def _date(value):
    if isinstance(value, date):
        return date.fromisoformat(value.isoformat())
    return date.fromisoformat(value)


def _time_range(raw):
    if not raw:
        return None, None
    # Visible period labels can be wrong (e.g. 上午 beside 14:00). Numeric 24h time wins.
    numeric = re.sub(r'上午|下午|晚上|早上|中午|凌晨', '', raw)
    match = re.fullmatch(r'\s*(\d{1,2}):(\d{2})\s*[-–—~至]\s*(\d{1,2}):(\d{2})\s*', numeric)
    if match:
        h1, m1, h2, m2 = map(int, match.groups())
        if 0 <= h1 <= 23 and 0 <= h2 <= 23 and 0 <= m1 <= 59 and 0 <= m2 <= 59:
            if (h1, m1) < (h2, m2):
                return f'{h1:02d}:{m1:02d}', f'{h2:02d}:{m2:02d}'
    return None, None


def parse_timetable(html, *, week_start=None, week_end=None):
    """Parse a rendered seven-column week, not a recurring schedule template.

    Dates are caller-supplied ISO values, or a full ISO range printed in the DOM.
    No current-date/year guesses, network access, credentials, or cache fallback.
    """
    result = {'schema_version': 1, 'source': 'hyqzedu', 'source_url': HOME,
              'fetched_at': None, 'parsed_at': now(), 'freshness': 'offline_unknown',
              'complete': False, 'data_status': 'unknown', 'week_start': None,
              'week_end': None, 'date_context_source': None, 'range_raw': None, 'displayed_year_raw': None,
              'lessons': [], 'days': [], 'exceptions': [], 'errors': [],
              'coverage': 'single_rendered_week_not_verified_live'}
    def error(code, **context):
        result['errors'].append({'code': code, **context})
    root = Tree(html).root
    cards = list(root.all(cls='schedule-card'))
    if len(cards) != 1:
        error('unrecognized_or_ambiguous_timetable_markup')
        return result
    card = cards[0]
    result['range_raw'] = txt(card.first(cls='header-week-range-text'))
    header = card.first(cls='y-ui__weekly-calendar__header')
    if header:
        first_child = next((n for n in header.children if isinstance(n, Node)), None)
        result['displayed_year_raw'] = txt(first_child)
    # Only a fully explicit ISO interval can be resolved without caller context.
    dates = re.findall(r'\b\d{4}-\d{2}-\d{2}\b', result['range_raw'] or '')
    dom_start = dom_end = None
    if len(dates) == 2:
        try:
            dom_start, dom_end = map(_date, dates)
        except (ValueError, TypeError):
            error('invalid_displayed_date_range')
            return result
    try:
        start = _date(week_start) if week_start is not None else dom_start
        end = _date(week_end) if week_end is not None else (start + timedelta(days=6) if start else None)
    except (ValueError, TypeError, OverflowError):
        error('invalid_date_context')
        return result
    if start is None:
        error('explicit_week_start_required')
        return result
    if end - start != timedelta(days=6):
        error('date_range_must_span_seven_days')
        return result
    short_range = re.fullmatch(r'\s*(\d{1,2})月(\d{1,2})日\s*-\s*(\d{1,2})月(\d{1,2})日\s*', result['range_raw'] or '')
    if short_range and tuple(map(int, short_range.groups())) != (start.month, start.day, end.month, end.day):
        error('date_context_mismatch')
        return result
    if dom_start is not None and (start != dom_start or end != dom_end):
        error('date_context_mismatch')
        return result
    displayed_year = re.fullmatch(r'\s*(\d{4})年?\s*', result['displayed_year_raw'] or '')
    if displayed_year and int(displayed_year[1]) not in {start.year, end.year}:
        error('displayed_year_context_mismatch')
        return result
    result.update(week_start=start.isoformat(), week_end=end.isoformat(),
                  date_context_source='caller_supplied' if week_start is not None else 'displayed_full_iso_range')
    cells = list(card.all(cls='y-ui__weekly-calendar__cell'))
    if len(cells) != 7:
        error('expected_seven_day_columns', actual_count=len(cells))
        return result
    # Labels are validation only, never a source for inferring missing dates.
    for index, cell in enumerate(cells):
        label = txt(cell.first(cls='cell-day')) or ''
        numeric_day = re.fullmatch(r'\s*(\d{1,2})日?\s*', label)
        if numeric_day and int(numeric_day[1]) != (start + timedelta(days=index)).day:
            error('day_label_context_mismatch', day_index=index)
    if result['errors']:
        return result
    for index, cell in enumerate(cells):
        day = (start + timedelta(days=index)).isoformat()
        day_info = {'date': day, 'day_index': index, 'weekday_raw': txt(cell.first(cls='cell-weekday')),
                    'day_label_raw': txt(cell.first(cls='cell-day')), 'data_status': 'unknown',
                    'lesson_count': 0}
        result['days'].append(day_info)
        for alert in cell.all(cls='el-alert__title'):
            if alert.text():
                result['exceptions'].append({'date': day, 'text': alert.text(), 'recurring': False})
        for position, item in enumerate(cell.all(cls='content-item')):
            raw_time = txt(item.first(cls='content-item__time'))
            begin, finish = _time_range(raw_time)
            lesson = {'source_id': None, 'date': day, 'day_index': index, 'position': position,
                      'time_raw': raw_time, 'start_time': begin, 'end_time': finish,
                      'timezone': None, 'course_name': txt(item.first(cls='content-item__course-name')),
                      'class_name': txt(item.first(cls='content-item__clazz-name')),
                      'room': txt(item.first(cls='content-item__address')), 'teacher': txt(item.first(cls='content-item__teacher')),
                      'recurring': False, 'exceptions': [n.text() for n in item.all(cls='el-alert__title') if n.text()]}
            result['lessons'].append(lesson)
            day_info['lesson_count'] += 1
            if begin is None:
                error('missing_or_unrecognized_lesson_time', date=day, position=position)
        if day_info['lesson_count']:
            day_info['data_status'] = 'observed_lessons'
    # Alerts outside day columns cannot safely be assigned to one date.
    for alert in card.all(cls='el-alert__title'):
        ancestor = alert.parent
        while ancestor is not None and ancestor not in cells:
            ancestor = ancestor.parent
        if ancestor is None and alert.text():
            result['exceptions'].append({'date': None, 'text': alert.text(), 'recurring': False})
            error('unscoped_timetable_alert')
    if result['lessons']:
        result['data_status'] = 'observed_lessons'
    else:
        result['data_status'] = 'data_unavailable'
        error('no_lessons_observed_not_proven_free')
    # Offline DOM may be stale, partial or mid-load. Never promise full live coverage.
    return result


class OfflineTimetableProvider:
    def __init__(self, html, *, week_start=None, week_end=None):
        self.html, self.week_start, self.week_end = html, week_start, week_end

    def read(self):
        return parse_timetable(self.html, week_start=self.week_start, week_end=self.week_end)


class UnconfiguredTimetableProvider:
    def read(self):
        return {'schema_version': 1, 'source': 'hyqzedu', 'source_url': HOME,
                'fetched_at': None, 'checked_at': now(), 'freshness': 'not_fetched',
                'complete': False, 'lessons': [],
                'errors': [{'code': 'provider_not_configured',
                            'message': 'Use offline rendered DOM; authenticated live provider is not installed.'}]}
