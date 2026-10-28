"""Rebuild the reviewed goods pack offline; never approve changed source bytes."""
import hashlib
import json
from pathlib import Path
import re
from tools.prepare_official_pack import Tree

BASE = Path(__file__).resolve().parents[1] / 'reference_data/office-goods-20261026'


def build(base=BASE):
    base = Path(base)
    rows = []
    for spec in json.loads((base / 'reviewed_sources.json').read_text(encoding='utf-8')):
        raw = (base / 'raw' / spec['raw_file']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != spec['raw_sha256']:
            raise ValueError('Reviewed original changed: ' + spec['raw_file'])
        tree = Tree(raw.decode('utf-8'))
        bodies = [n for n in tree.root.walk() if 'lawcon' in n.attrs.get('class', '').split()]
        if len(bodies) != 1:
            raise ValueError('Expected one complete article')
        text = '\n'.join(n.text() for n in bodies[0].walk() if n.tag == 'p' and n.text()) + '\n'
        if not text.startswith(spec['article']):
            raise ValueError('Unexpected article heading')
        row = dict(spec, sha256=hashlib.sha256(text.encode('utf-8')).hexdigest(),
                   units=[dict(loc=spec['article'] + ' 全文', text=text.strip())])
        (base / 'excerpts').mkdir(exist_ok=True)
        (base / 'excerpts' / row['filename']).write_bytes(text.encode('utf-8'))
        rows.append(row)
    (base / 'manifest.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    return rows


if __name__ == '__main__':
    print(json.dumps(dict(articles=len(build()), network_used=False), ensure_ascii=False))
