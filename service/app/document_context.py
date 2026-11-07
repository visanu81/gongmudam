"""Separate document identifiers from event dates; leave source text intact.

Ported from the teammate branch (BC3-r7, F-EVENT-MONTH-01, R7-MONTH-PARTICLE).
"""
import re
from datetime import date

_NUMBER = re.compile(r'(?:제\s*)?(?:19|20)\d{2}\s*[-–—−]\s*\d+\s*호')
_DATE = re.compile(r'(?<!\d)((?:19|20)\d{2})\s*(?:[-./]|년)\s*(\d{1,2})\s*(?:[-./]|월)\s*(\d{1,2})(?:일)?(?!\d)')
_MONTH = re.compile(r'(?<!\d)((?:19|20)\d{2})\s*(?:년\s*(\d{1,2})\s*월|[-./]\s*(\d{1,2})(?!\d)(?=$|[^\d가-힣]|(?:에(?:는|도|서)?|의|은|는|부터|까지|경)(?=\s|$|[.,!?？。;])))')


def without_document_numbers(text):
    return _NUMBER.sub(' ', text)


def event_years(text):
    return set(re.findall(r'(?<!\d)(?:19|20)\d{2}(?!\d)', without_document_numbers(text)))


def event_dates(text):
    """Full explicit dates only; document identifiers are excluded."""
    dates = set()
    for match in _DATE.finditer(without_document_numbers(text)):
        try:
            dates.add(date(*(int(v) for v in match.groups())))
        except ValueError:
            continue
    return dates


def event_months(text):
    """Incomplete year/month clues, not inferred incident dates.

    Full date spans and document identifiers are excluded. Raw invalid month
    components remain visible so the source selector can hold them safely.
    """
    remaining = _DATE.sub('', without_document_numbers(text))
    return {(int(m[1]), int(m[2] or m[3])) for m in _MONTH.finditer(remaining)}
