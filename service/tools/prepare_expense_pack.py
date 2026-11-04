"""Rebuild the 업무추진비 disclosure pack offline from the two hash-checked originals.

The originals are the same 지방회계관리훈령 PDF and 2026 집행지침 HWPX the finance
pack reviewed; only the disclosure sections are cut, by page or paragraph.

usage (from service/): python -X utf8 -m tools.prepare_expense_pack
"""
import hashlib
import json
from pathlib import Path

from tools.collect_finance_pack import NATIONAL_SHA, clip

BASE = Path(__file__).resolve().parents[1] / 'reference_data/office-expense-20261104'
FINANCE = BASE.parent / 'finance-20261025'


def local_units(raw):
    from io import BytesIO
    from pypdf import PdfReader
    pages = [p.extract_text() or '' for p in PdfReader(BytesIO(raw)).pages]
    if len(pages) != 222 or '제446호' not in pages[0].replace(' ', ''):
        raise ValueError('Unexpected local edition')
    article = clip(pages[46], '제121조(집행현황의 공개)', '3.장기근속')
    if '《공개방법》' not in pages[76][:30] or '2-3. 공개방법' not in pages[77]:
        raise ValueError('Unexpected disclosure page')
    # One unit: the answer quotes the article and the annex together.
    return [dict(loc='PDF 47쪽 제121조 · 77~78쪽 《공개방법》', text='\n'.join((article, pages[76].strip(), pages[77].strip())))]


def national_units(section, start, end):
    # The paragraph numbers are those of the finance pack's saved extraction of
    # the same HWPX; the current extractor numbers paragraphs differently.
    n = json.loads((FINANCE / 'national-full-text.json').read_text(encoding='utf-8'))
    if n['status'] != 'ready':
        raise ValueError('National original was not fully extracted')
    wanted = {f'{section}구역 {i}문단' for i in range(start, end + 1)}
    text = '\n'.join(u['text'] for u in n['units'] if u['loc'] in wanted)
    if not text.startswith('4. 업무추진비') or '기관장의 업무추진비 사용내역' not in text.splitlines()[-1]:
        raise ValueError('Unexpected national section')
    return [dict(loc=f'HWPX {section}구역 {start}~{end}문단', text=text)]


def build(base=BASE):
    base = Path(base)
    rows = []
    for spec in json.loads((base / 'reviewed_sources.json').read_text(encoding='utf-8')):
        path = base / 'raw' / spec['raw_file']
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != spec['raw_sha256']:
            raise ValueError('Reviewed original changed: ' + spec['raw_file'])
        if 'pdf_pages' in spec:
            units = local_units(raw)
        elif spec['raw_sha256'] == NATIONAL_SHA:
            units = national_units(*spec['hwpx_paragraphs'])
        else:
            raise ValueError('National text was extracted from a different original')
        text = '\n'.join(u['text'] for u in units) + '\n'
        row = dict(spec, sha256=hashlib.sha256(text.encode('utf-8')).hexdigest(), units=units)
        (base / 'excerpts').mkdir(exist_ok=True)
        (base / 'excerpts' / row['filename']).write_bytes(text.encode('utf-8'))
        rows.append(row)
    (base / 'manifest.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    return rows


if __name__ == '__main__':
    print(json.dumps(dict(sections=len(build()), network_used=False), ensure_ascii=False))
