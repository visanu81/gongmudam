"""Rebuild the reviewed 선금 pack offline; never approve changed source bytes.

Laws and the national 계약예규 are saved law.go.kr article pages (one
``lawcon`` article each). The local 집행기준 is only published as a document
viewer, so its 제1장 제2절 is rebuilt from the saved page XML of that viewer,
from the section heading up to the next item, with page numbers removed.

usage (from service/): python -X utf8 -m tools.prepare_advance_pack
"""
import hashlib
import html
import json
from pathlib import Path
import re
from tools.prepare_official_pack import Tree

BASE = Path(__file__).resolve().parents[1] / 'reference_data/office-advance-20261104'


def _raw(base, name, sha):
    raw = (base / 'raw' / name).read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha:
        raise ValueError('Reviewed original changed: ' + name)
    return raw.decode('utf-8')


def _article(raw, heading):
    bodies = [n for n in Tree(raw).root.walk() if 'lawcon' in n.attrs.get('class', '').split()]
    found = []
    for body in bodies:
        text = '\n'.join(n.text() for n in body.walk() if n.tag == 'p' and n.text())
        if text.startswith(heading):
            # A formula published as an image leaves only its file id in the text.
            found.append(re.sub(r'img\d{6,}', ' [산식 그림]', text))
    if len(found) != 1:
        raise ValueError('Expected one complete article: ' + heading)
    return found[0] + '\n'


def _pages(base, spec):
    lines = []
    for name, sha in zip(spec['raw_files'], spec['raw_sha256s']):
        page = _raw(base, name, sha)
        for para in re.findall(r'<paragraph[^>]*>(.*?)</paragraph>', page, re.S):
            line = ''.join(html.unescape(t) for t in re.findall(r'<text[^>]*>(.*?)</text>', para, re.S))
            line = re.sub(r'\s*- \d+ -\s*$', '', line)
            if line.strip():
                lines.append(line.rstrip())
    text = '\n'.join(lines)
    start, end = text.find(spec['start']), text.find(spec['end'])
    if start < 0 or end <= start or text.count(spec['start']) != 1:
        raise ValueError('Section markers not found: ' + spec['article'])
    return text[start:end].rstrip() + '\n'


def build(base=BASE):
    base = Path(base)
    rows = []
    for spec in json.loads((base / 'reviewed_sources.json').read_text(encoding='utf-8')):
        if 'raw_files' in spec:
            text = _pages(base, spec)
        else:
            text = _article(_raw(base, spec['raw_file'], spec['raw_sha256']), spec['article'])
        row = dict(spec, sha256=hashlib.sha256(text.encode('utf-8')).hexdigest(),
                   units=[dict(loc=spec['article'] + ' 全文', text=text.strip())])
        (base / 'excerpts').mkdir(exist_ok=True)
        (base / 'excerpts' / row['filename']).write_bytes(text.encode('utf-8'))
        rows.append(row)
    (base / 'manifest.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    return rows


if __name__ == '__main__':
    print(json.dumps(dict(sources=len(build()), network_used=False), ensure_ascii=False))
