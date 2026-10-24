"""Observed ManageBac HTML selectors, isolated from storage and authentication."""
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, urlsplit, parse_qs
from .html import Tree, txt

ORIGIN = 'https://sdgj.managebac.cn'
TASKS = ORIGIN + '/student/tasks_and_deadlines'
CLASSES = ORIGIN + '/student/classes/my'
VIEWS = ('upcoming', 'past', 'overdue')


class ReaderError(Exception):
    """Safe error code only: never include remote content or session secrets."""


def now():
    return datetime.now(timezone.utc).isoformat()


def safe_url(url):
    try:
        p = urlsplit(url)
        if (p.scheme != 'https' or p.hostname != 'sdgj.managebac.cn'
                or p.port not in (None, 443) or p.username or p.password or p.fragment):
            return False
        if p.path == '/student/tasks_and_deadlines':
            q = parse_qs(p.query, keep_blank_values=True)
            return all(k in {'view', 'page'} and len(v) == 1 for k, v in q.items()) and (
                'view' not in q or q['view'][0] in VIEWS) and (
                'page' not in q or re.fullmatch(r'[1-9]\d*', q['page'][0]) is not None)
        return not p.query and (p.path == '/student/classes/my' or
            re.fullmatch(r'/student/classes/\d+(?:/core_tasks(?:/\d+)?)?', p.path) is not None)
    except ValueError:
        return False


def document(html):
    root = Tree(html).root
    if any(n.attrs.get('type') == 'password' or n.attrs.get('name') == 'password'
           or n.attrs.get('id') in {'session_login', 'session_password'} for n in root.all('input')):
        raise ReaderError('authentication_required')
    title = txt(root.first('title')) or ''
    if re.search(r'ManageBac\s*\|\s*Login', title, re.I):
        raise ReaderError('authentication_required')
    return root


def provenance(url, at, mode='live'):
    return {'source': 'managebac', 'source_url': url,
            'fetched_at': at if mode == 'live' else None,
            'parsed_at': at,
            'freshness': 'fetched_this_run' if mode == 'live' else 'offline_unknown',
            'evidence': 'official_page', 'estimated': False}


def due_date(raw):
    # Do not manufacture a year, time or timezone for incomplete dates.
    if not raw:
        return {'raw': None, 'value': None, 'precision': 'unknown'}
    for fmt in ('%b %d, %Y, %I:%M %p', '%B %d, %Y, %I:%M %p'):
        try:
            dt = datetime.strptime(raw, fmt).replace(tzinfo=timezone(timedelta(hours=8)))
            return {'raw': raw, 'value': dt.isoformat(), 'precision': 'minute',
                    'timezone_assumption': 'Asia/Shanghai'}
        except ValueError:
            pass
    return {'raw': raw, 'value': None, 'precision': 'unresolved'}


def parse_tasks(html, url=TASKS, fetched_at=None, view='upcoming', mode='live'):
    if view not in VIEWS:
        raise ValueError('Unknown view')
    root = document(html)
    container = root.first(cls='js-tasks')
    if container is None:
        raise ReaderError('unrecognized_tasks_markup')
    records, date_header, errors = [], None, []
    for child in container.children:
        if isinstance(child, str):
            continue
        if child.has('text-secondary') and child.has('mb-n2'):
            date_header = child.text()
        tiles = [child] if child.has('f-task-tile') else list(child.all(cls='f-task-tile'))
        for tile in tiles:
            a = tile.first('a', 'f-tile__title-link')
            try:
                href = urljoin(ORIGIN, a.attrs.get('href', '')) if a else ''
            except ValueError:
                errors.append({'code': 'invalid_task_identity'})
                continue
            m = re.search(r'/core_tasks/(\d+)$', urlsplit(href).path)
            if not a or not a.text() or not m or not safe_url(href):
                errors.append({'code': 'invalid_task_identity'})
                continue
            desc = tile.first(cls='f-tile__description')
            raw_date, course = None, None
            if desc:
                course = txt(desc.first('a', 'link-dark'))
                for span in desc.all('span'):
                    if not span.has('vr') and (span.first('svg') or re.search(
                            r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)', span.text())):
                        raw_date = span.text() or None
                        break
            score = tile.first(cls='f-task-score')
            status = ('Assessed' if score and score.has('f-task-score--assessment') else
                      'Not Assessed' if score and score.has('f-task-score--not-assessed') else txt(score))
            records.append({'id': 'core_task:' + m.group(1), 'title': a.text(), 'url': href,
                'course_name': course, 'date_header': date_header, 'due': due_date(raw_date or date_header),
                'status': status, 'score_raw': txt(score.first('h4')) if score else None,
                'points_raw': txt(score.first('p')) if score else None, 'views': [view],
                'provenance': provenance(url, fetched_at or now(), mode)})
    next_urls = []
    for a in root.all('a'):
        if (a.has('next') or 'next' in (a.attrs.get('rel') or '').split()
                or 'Show More' in a.text()):
            href = a.attrs.get('href')
            if not href:
                if a.attrs.get('aria-disabled') == 'true' or a.has('disabled'):
                    continue
                raise ReaderError('missing_pagination_url')
            if href:
                try:
                    target = urljoin(url, href)
                except ValueError:
                    raise ReaderError('unsafe_pagination_url') from None
                if not safe_url(target) or urlsplit(target).path != urlsplit(TASKS).path:
                    raise ReaderError('unsafe_pagination_url')
                q = parse_qs(urlsplit(target).query)
                if 'view' not in q:
                    raise ReaderError('pagination_view_missing')
                if q['view'][0] != view:
                    raise ReaderError('pagination_view_changed')
                next_urls.append(target)
    if len(set(next_urls)) > 1:
        raise ReaderError('ambiguous_pagination')
    return records, next_urls[0] if next_urls else None, errors


def parse_classes(html):
    root = document(html)
    classes = {}
    for a in root.all('a'):
        try:
            href = urljoin(ORIGIN, a.attrs.get('href', ''))
        except ValueError:
            raise ReaderError('invalid_class_url') from None
        m = re.fullmatch(r'/student/classes/(\d+)', urlsplit(href).path)
        if m and safe_url(href) and a.text():
            classes[m.group(1)] = a.text()
    if not classes and not root.first(cls='js-menu-classes-list'):
        raise ReaderError('unrecognized_classes_markup')
    return classes


def parse_grades(html, class_id, class_name, url, fetched_at=None, mode='live'):
    root = document(html)
    sidebar = root.first(cls='sidebar-items-list')
    if sidebar is None:
        raise ReaderError('unrecognized_grades_markup')
    categories, overall = [], None
    for item in sidebar.all(cls='list-item'):
        cells = list(item.all(cls='cell'))
        if len(cells) < 2:
            continue
        label = txt(cells[0].first(cls='label')) or cells[0].text()
        raw = cells[1].text()
        if label == 'Category (Weight)':
            continue
        weight = re.search(r'\((\d+(?:\.\d+)?)\s*%\)', label)
        percent = re.search(r'(\d+(?:\.\d+)?)\s*%', raw)
        result = {'name': re.sub(r'\s*\([\d.]+\s*%\)\s*$', '', label),
                  'weight_percent': float(weight[1]) if weight else None,
                  'grade_raw': txt(cells[1].first('strong')),
                  'percentage': float(percent[1]) if percent else None, 'raw_value': raw,
                  'estimated': False}
        if label.startswith('Overall'):
            overall = result
        else:
            categories.append(result)
    if overall is None and not categories:
        raise ReaderError('unrecognized_grades_values')
    return {'class_id': class_id, 'class_name': class_name, 'overall': overall,
            'categories': categories, 'grade_boundaries': None,
            'boundaries_status': 'not_read', 'estimated_grade': None,
            'provenance': provenance(url, fetched_at or now(), mode)}


def merge_tasks(records):
    """Last observation wins (including nulls); retain all observed views.

    No old cache is read: missing or failed pages never silently reuse stale values.
    Conflicting non-null fields are reported, not reconciled by guessed chronology.
    """
    merged, conflicts = {}, []
    for record in records:
        key = record['id']
        old = merged.get(key)
        current = dict(record)
        if old:
            changed = [k for k in ('title', 'due', 'status', 'score_raw', 'points_raw')
                       if old.get(k) != current.get(k)]
            if changed:
                conflicts.append({'code': 'conflicting_observations', 'id': key, 'fields': changed,
                                  'resolution': 'last_observation_wins'})
            current['views'] = sorted(set(old['views'] + current['views']))
        merged[key] = current
    return list(merged.values()), conflicts


class ManageBacReader:
    def __init__(self, transport, max_pages=30):
        if not 1 <= max_pages <= 1000:
            raise ValueError('max_pages must be between 1 and 1000')
        self.transport, self.max_pages = transport, max_pages

    def read(self, include_grades=True):
        result = {'schema_version': 1, 'source': 'managebac', 'started_at': now(),
                  'freshness': 'fetched_this_run', 'complete': True, 'tasks': [], 'grades': [],
                  'errors': [], 'pagination': {}}
        records = []
        def error(code, scope):
            result['complete'] = False
            result['errors'].append({'code': code, 'scope': scope})
        for view in VIEWS:
            url, seen = TASKS + '?view=' + view, set()
            info = {'pages_read': 0, 'complete': False}
            result['pagination'][view] = info
            try:
                while url:
                    if url in seen:
                        raise ReaderError('pagination_cycle')
                    if len(seen) >= self.max_pages:
                        raise ReaderError('pagination_limit')
                    seen.add(url)
                    page = self.transport.get(url)
                    rows, following, issues = parse_tasks(page, url, now(), view)
                    records.extend(rows)
                    info['pages_read'] += 1
                    for issue in issues:
                        error(issue['code'], view)
                    url = following
                info['complete'] = True
            except ReaderError as exc:
                error(str(exc), view)
        result['tasks'], conflicts = merge_tasks(records)
        for issue in conflicts:
            result['errors'].append(issue)
        if conflicts:
            result['complete'] = False
        if include_grades:
            try:
                classes = parse_classes(self.transport.get(CLASSES))
                for class_id, class_name in classes.items():
                    url = ORIGIN + f'/student/classes/{class_id}/core_tasks'
                    try:
                        result['grades'].append(parse_grades(self.transport.get(url), class_id, class_name, url))
                    except ReaderError as exc:
                        error(str(exc), 'class:' + class_id)
            except ReaderError as exc:
                error(str(exc), 'classes')
        result['finished_at'] = now()
        return result
