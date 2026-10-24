"""Separate provider contract. No undocumented school endpoints are guessed."""
from typing import Protocol
from .managebac import now

HOME = 'https://student.hyqzedu.com/app-base-info/app/home'


class TimetableProvider(Protocol):
    def read(self) -> dict:
        """Return source, fetched_at, freshness, complete, lessons and errors.

        Verified adapters should retain source lesson IDs, dates/timezones, course,
        room and teacher as optional fields; do not infer recurring weeks.
        """
        ...


class UnconfiguredTimetableProvider:
    def read(self):
        return {'schema_version': 1, 'source': 'hyqzedu', 'source_url': HOME,
                'fetched_at': None, 'checked_at': now(), 'freshness': 'not_fetched',
                'complete': False, 'lessons': [],
                'errors': [{'code': 'provider_not_configured',
                            'message': 'Verified read endpoint and redacted response sample required.'}]}
