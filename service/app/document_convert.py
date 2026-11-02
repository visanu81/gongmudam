"""Structure-preserving conversion for project files (2026-11-01).

skdconv (Python) reads HWP and HWPX; kordoc (Node.js) reads PDF
when it is installed. Both return paragraphs and tables with their cells, so
a table row is stored with its column headers ("부서: 회계과 / 참석 인원: 0")
instead of one cell per line. When a converter is missing or fails, the
caller falls back to the built-in extractor. Measured on synthetic and public
documents in docs/research/문서변환기_비교_20261101.md.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile

SERVICE = Path(__file__).resolve().parents[1]
# DOCX and XLSX stay with the built-in reader: it already kept every table row
# (100%, 6/6) and also reads headers, footers and formula status.
STRUCTURED = {'.hwp', '.hwpx'}
KORDOC_SECONDS = 90
# Defaults for the bundled install (tools/install_kordoc.py) and the container image.
KORDOC_CANDIDATES = (SERVICE.parent / '.local-runtime/kordoc/node_modules/kordoc/dist/cli.js',
                     Path('/opt/kordoc/node_modules/kordoc/dist/cli.js'))


class ConvertError(Exception):
    pass


def kordoc_cli():
    """(node, cli) when kordoc can run here, else None."""
    configured = os.environ.get('GONGMUDAM_KORDOC_CLI')
    candidates = [Path(configured)] if configured else list(KORDOC_CANDIDATES)
    cli = next((p for p in candidates if p.is_file()), None)
    node = os.environ.get('GONGMUDAM_NODE') or shutil.which('node')
    return (node, cli) if cli and node else None


def _skdconv_blocks(path):
    import skdconv
    result = skdconv.parse(Path(path).read_bytes())
    if not getattr(result, 'success', False):
        raise ConvertError(str(getattr(result, 'error', '') or '변환 실패'))
    blocks = []
    for b in result.blocks:
        table = None
        if b.table is not None:
            table = [[(c.text or '', c.col_span or 1, c.row_span or 1) for c in row] for row in b.table.cells]
        blocks.append({'type': b.type, 'text': b.text or '', 'page': b.page_number, 'table': table})
    return blocks


def _kordoc_blocks(path):
    found = kordoc_cli()
    if not found:
        raise ConvertError('kordoc 미설치')
    node, cli = found
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / 'out.json'
        flags = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
        try:
            subprocess.run([node, str(cli), str(Path(path).resolve()), '--format', 'json', '-o', str(target)], cwd=str(cli.parent),
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=KORDOC_SECONDS, check=True, **flags)
            data = json.loads(target.read_text(encoding='utf-8'))
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            raise ConvertError('kordoc 변환 실패') from error
    if not data.get('success'):
        raise ConvertError('kordoc 변환 실패')
    blocks = []
    for b in data.get('blocks', []):
        table = None
        if b.get('table'):
            table = [[(c.get('text') or '', c.get('colSpan') or 1, c.get('rowSpan') or 1) for c in row]
                     for row in b['table'].get('cells', [])]
        blocks.append({'type': b.get('type'), 'text': b.get('text') or '', 'page': b.get('pageNumber'), 'table': table})
    return blocks


def _grid(rows):
    """Expand merged cells so every row has a value under each column."""
    grid, pending = [], {}
    width = max((len(row) for row in rows), default=0)
    for row in rows:
        line, col, cells = [], 0, list(row)
        # Spreadsheets also list the cells a merge covers; drop those so values keep their columns.
        if sum(span for _, span, _ in cells) > width:
            kept = []
            for text, span, down in cells:
                if kept and not text.strip() and kept[-1][3] > 0:
                    kept[-1][3] -= 1
                    continue
                kept.append([text, span, down, span - 1])
            cells = [(text, span, down) for text, span, down, _ in kept]
        while cells or pending.get(col):
            if pending.get(col):
                text, left = pending[col]
                line.append(text)
                pending[col] = (text, left - 1) if left > 1 else None
                col += 1
                continue
            text, colspan, rowspan = cells.pop(0)
            for _ in range(max(1, colspan)):
                line.append(text.strip())
                if rowspan > 1:
                    pending[col] = (text.strip(), rowspan - 1)
                col += 1
        grid.append(line)
    return grid


# A cell that only names a field: short words, no digits, checkboxes or sentences.
LABEL = re.compile(r'^[가-힣A-Za-z()·/\s]{1,15}$')


def _weak(header):
    """A first row that is a choice or a sentence, not column names (a form's 참가 구분 | ■ 개인 □ 팀)."""
    values = [v for v in dict.fromkeys(header) if v]
    return len(values) < 2 or any('■' in v or '□' in v or len(v) > 30 for v in values)


def _pairs(values):
    """A form row: "label: value", led by its group label when there is one."""
    flat = [v.replace('\n', ' ') for v in values]
    lead = [flat.pop(0)] if len(flat) % 2 else []
    pairs = [f'{flat[i]}: {flat[i + 1]}' for i in range(0, len(flat), 2)]
    return ' · '.join(lead + [' / '.join(pairs)] if pairs else lead)


def _table_units(rows):
    """(label, text) per row; data rows carry their column headers.

    Forms put labels beside values and start new header rows midway
    (구분 | 성명 | 부서 above a person's row); those are read as such.
    """
    grid = _grid(rows)
    header_index = next((i for i, r in enumerate(grid) if len({v for v in r if v}) >= 2), None)
    header = grid[header_index] if header_index is not None else None
    section, header_at, last = False, header_index, None
    units = []
    for i, row in enumerate(grid):
        values = [v for v in dict.fromkeys(row) if v]
        if not values:
            continue
        previous_row, last = last, i
        if header_index is None or i <= header_index:
            units.append((f'{i + 1}행', ' | '.join(values)))
            continue
        labels = len(values) >= 3 and all(LABEL.match(v) for v in values)
        # A group label merged down the rows (기관 정보 beside 기관명 and 담당부서명)
        # marks label-value rows, not a header over the next row.
        below = next((r for r in grid[i + 1:] if any(r)), None)
        labels = labels and bool(below) and len({v for v in below if v}) >= 3 and not (below[0] and below[0] == row[0])
        # Under real column names only the row right below can add a second level;
        # later rows of short words are data (예산전용 | 확정 | 사유발생시).
        # A second level splits a heading merged across columns (운임 over FIRST | BUSINESS).
        second = previous_row == header_at and any(
            header[c] and header[c] == header[c + 1] and row[c] != row[c + 1] for c in range(min(len(header), len(row)) - 1))
        if labels and (_weak(header) or second):
            if not _weak(header):
                # A second header row under the first (’26년 예산액 over 금액 | 구성비): name both.
                header = [c if p in ('', c) else p if c in ('', p) else f'{p} {c}'
                          for p, c in zip(header + [''] * len(row), row)]
            else:
                header, section = row, True
            header_at = i
            units.append((f'{i + 1}행', ' | '.join(v.replace('\n', ' ') for v in values)))
            continue
        if section and len(values) < 3:
            # The people block above is over; back to label-value rows.
            header, section, header_at = grid[header_index], False, header_index
        if _weak(header):
            units.append((f'{i + 1}행', _pairs(values)))
            continue
        parts, previous = [], None
        for col, value in enumerate(row):
            name = header[col] if col < len(header) else ''
            # A merged cell repeats across columns; say it once.
            if not value or value == previous:
                continue
            previous = value
            parts.append(f'{name}: {value}' if name and name != value else value)
        units.append((f'{i + 1}행', ' / '.join(parts)))
    return units


def convert(path, add):
    """Fill `add(loc, text)` from the structured converter; return its name, or raise ConvertError."""
    suffix = Path(path).suffix.lower()
    if suffix == '.pdf':
        blocks, name = _kordoc_blocks(path), 'kordoc'
    elif suffix in STRUCTURED:
        try:
            blocks, name = _skdconv_blocks(path), 'skdconv'
        except ImportError as error:
            raise ConvertError('skdconv 미설치') from error
        except ConvertError:
            raise
        except Exception as error:  # A damaged file must not stop the fallback extractor.
            raise ConvertError('skdconv 변환 실패') from error
    else:
        raise ConvertError('구조 변환 대상 아님')
    if not any(b['text'].strip() or b['table'] for b in blocks):
        raise ConvertError('변환 결과 없음')
    paragraph = table_no = 0
    section = ''
    for b in blocks:
        page = f"{b['page']}쪽 " if suffix == '.pdf' and b['page'] else ''
        if b['type'] == 'heading' and suffix == '.xlsx':
            section = b['text'].strip() + ' · '
            continue
        if b['table']:
            table_no += 1
            for label, text in _table_units(b['table']):
                add(f'{page}{section}표 {table_no} {label}', text)
            continue
        if b['text'].strip():
            paragraph += 1
            add(f'{page}{section}{paragraph}문단', b['text'].strip())
    return name
