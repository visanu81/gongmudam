"""Dates in a 업무자료 정리 answer, offered as work-calendar entries the user confirms.

Office documents write dates as "11. 13.(목)", "2026년 11월 13일" or "11/13", often without
a year. Nothing is registered here: each candidate keeps its source line and says when
the year was not written, and the screen asks the user to check it before saving.
"""
from datetime import date
import re

FULL = re.compile(r'(20\d{2})\s*(?:[.\-/]|년)\s*(\d{1,2})\s*(?:[.\-/]|월)\s*(\d{1,2})\s*(?:일|\.)?')
# "11. 13." needs both dots so "1. 법령" or "3.5" are not dates; "11월 13일" and "11/13" are.
SHORT = re.compile(r'(?<![\d.,])(\d{1,2})(?:\.\s?(\d{1,2})\.|월\s*(\d{1,2})일|/(\d{1,2})(?![\d/]))')
RANGE = re.compile(r'^\s*[(（]?[월화수목금토일]?[)）]?\s*(?:\d{1,2}:\d{2}\s*)?[~∼〜-]')
DEADLINE = re.compile(r'마감|기한|까지|제출|회신')
SOURCE = re.compile(r'^\s*-\s*([^:]{1,120}\.[A-Za-z0-9]{2,5}):\s*')
REF = re.compile(r'\s*\[\d+\]\s*$')
LIMIT = 20


def _dates(line, today):
    """(start offset, end offset, date, year written) for each valid date in the line."""
    found, taken = [], []
    for m in FULL.finditer(line):
        try:
            found.append((m.start(), m.end(), date(int(m[1]), int(m[2]), int(m[3])), True))
            taken.append(range(m.start(), m.end()))
        except ValueError:
            pass
    for m in SHORT.finditer(line):
        if any(m.start() in r for r in taken):
            continue
        day = m[2] or m[3] or m[4]
        try:
            found.append((m.start(), m.end(), date(today.year, int(m[1]), int(day)), False))
        except ValueError:
            pass
    return sorted(found)


def candidates(content, today, project_name=''):
    """Calendar candidates from the answer's lines, in order, at most twenty."""
    out, seen = [], set()
    for raw in (content or '').splitlines():
        found = _dates(raw, today)
        if not found:
            continue
        source = SOURCE.match(raw)
        text = REF.sub('', raw[source.end():] if source else raw.lstrip('- ')).strip()
        first = found[0]
        # "11. 13.(목) ~ 11. 14." is one event over two days.
        end = found[1] if len(found) > 1 and RANGE.match(raw[first[1]:found[1][0]]) else None
        groups = [(first, end)] if end else [(d, None) for d in found]
        for start, until in groups:
            last = until[2] if until else start[2]
            if until and start[3] and not until[3]:
                # "2026. 12. 1. ~ 12. 3." writes the year once, on the start.
                try:
                    last = last.replace(year=start[2].year + (last.replace(year=start[2].year) < start[2]))
                except ValueError:  # 2월 29일 in a year without one
                    continue
            if last < start[2] or (start[2], last, text) in seen:
                continue
            seen.add((start[2], last, text))
            title = text if len(text) <= 80 else text[:79] + '…'
            out.append(dict(title=f'{project_name} · {title}' if project_name else title, start=start[2].isoformat(),
                            end=last.isoformat(), year_written=start[3],
                            kind='deadline' if DEADLINE.search(raw) else 'event',
                            line=text, source=source[1] if source else ''))
            if len(out) >= LIMIT:
                return out
    return out
