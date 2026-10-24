"""Offline CLI only. Live use is explicitly injected through the Python API."""
import argparse
import json
from pathlib import Path
from .managebac import parse_tasks, parse_grades, merge_tasks, now, TASKS, ORIGIN, ReaderError
from .timetable import UnconfiguredTimetableProvider


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    tasks = sub.add_parser('tasks', help='Parse an HTML export without network access')
    tasks.add_argument('html', type=Path)
    tasks.add_argument('--view', choices=('upcoming', 'past', 'overdue'), default='upcoming')
    tasks.add_argument('--timezone', help='Verified account IANA timezone, e.g. Asia/Shanghai; no default')
    grades = sub.add_parser('grades', help='Parse a class core_tasks HTML export')
    grades.add_argument('html', type=Path)
    grades.add_argument('--class-id', required=True, type=int)
    grades.add_argument('--class-name', default='')
    sub.add_parser('timetable-status')
    args = parser.parse_args()
    try:
        if args.command == 'timetable-status':
            result = UnconfiguredTimetableProvider().read()
        elif args.command == 'tasks':
            rows, next_url, errors = parse_tasks(args.html.read_text(encoding='utf-8'),
                                                TASKS, now(), args.view, 'offline', timezone_name=args.timezone)
            rows, conflicts = merge_tasks(rows)
            result = {'schema_version': 1, 'source': 'managebac', 'freshness': 'offline_unknown',
                      'complete': False, 'tasks': rows, 'next_url': next_url,
                      'errors': errors + conflicts,
                      'coverage': 'single_offline_page_not_verified_live'}
        else:
            url = ORIGIN + f'/student/classes/{args.class_id}/core_tasks'
            result = {'schema_version': 1, 'source': 'managebac', 'freshness': 'offline_unknown',
                      'complete': False, 'errors': [], 'coverage': 'single_offline_class_page',
                      'grades': [parse_grades(args.html.read_text(encoding='utf-8'),
                          str(args.class_id), args.class_name, url, now(), 'offline')]}
    except (ReaderError, OSError, UnicodeError) as exc:
        # File paths/HTML/credentials are never included in errors.
        result = {'complete': False, 'errors': [{'code': str(exc) if isinstance(exc, ReaderError)
                                               else 'offline_file_read_error'}]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get('errors') else 0


if __name__ == '__main__':
    raise SystemExit(main())
