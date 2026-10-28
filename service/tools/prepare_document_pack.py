"""Reproduce reviewed complete articles from pinned official HTML, offline.

This is not an updater or approval mechanism. Changed source bytes must be
reviewed before changing the pinned hashes or the separately reviewed Q&A.
"""
import hashlib
import json
from pathlib import Path
import re

from tools.prepare_official_pack import Tree

BASE = Path(__file__).resolve().parents[1] / 'reference_data/office-documents-20261026'
PINS = {
    2: 'eac5b00571741822392cae636b4263babe5579d11ffb184896fc4fafa81bf561',
    3: '449edec49aa746676b992aca1edff76fec5b91cd7352eeac58e9e011611b1213',
    6: '793674eaf86787072ff609cbe9b741c789830be5d06804f62652bfb02ff2a7bc',
    8: 'd24d543ae30b109a54ee0d3794aaae459bdd6d4389c1db6491cb8667215c167b',
    9: 'c6899c322e332a6977b37cddceeeeede2f76273faab94e9238fa34982d63a88e',
    10: '49ee66067b0cb328029327273cdc206caad126934212a6c4d6e7c90478af2ee6',
    11: 'e44f5755bf329699418e2edad236d563e04b584d5f9995c9663093d67c052d6f',
    12: 'e5aa3ae422c7a6c36360da751857d36faa389f05ef8691059f0b1a87df94c486',
    18: '36d2d5e5fef3c6d82459ba8c3dc8632294adb314c02e8584fda09c1f24cab66f',
    15: '08268a866afc01b2cbae4c38fe9e193f2e320c10734111c41e1aaf21d31f34c6',
}


def build(base=BASE):
    base = Path(base)
    rows = []
    for number, expected in PINS.items():
        rule = number == 15
        seq = 252189 if rule else 290525
        stem = f'administration-{"rules-" if rule else ""}{seq}-{number}'
        raw_name = stem + '.html'
        raw = (base / 'raw' / raw_name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('Reviewed original changed: ' + raw_name)
        tree = Tree(raw.decode('utf-8'))
        bodies = [n for n in tree.root.walk() if 'lawcon' in n.attrs.get('class', '').split()]
        if len(bodies) != 1:
            raise ValueError('Expected one complete article: ' + raw_name)
        paragraphs = [n.text() for n in bodies[0].walk() if n.tag == 'p' and n.text()]
        text = '\n'.join(paragraphs) + '\n'
        match = re.match(rf'^(제{number}조\([^)]*\))', text)
        if not match:
            raise ValueError('Unexpected article: ' + raw_name)
        title = '행정업무의 운영 및 혁신에 관한 규정' + (' 시행규칙' if rule else '')
        file_id = f'office-documents-{"rule" if rule else "decree"}-{number}'
        filename = file_id + '.txt'
        excerpt = text.encode('utf-8')
        rows.append(dict(
            id=file_id, title=title, article=match[1], filename=filename,
            sha256=hashlib.sha256(excerpt).hexdigest(), kind='법령·규정', issuer='행정안전부',
            institution='행정기관 · 다른 법령에 특별한 규정이 있으면 해당 규정 확인',
            effective_date='2023-06-28' if rule else '2026-10-02',
            publication='행정안전부령 제408호, 2023. 6. 28., 일부개정' if rule else '대통령령 제36728호, 2026. 9. 29., 타법개정',
            source_url=f'https://www.law.go.kr/LSW/lsSideInfoP.do?docCls=jo&joBrNo=00&joNo={number:04d}&lsiSeq={seq}&urlMode=lsScJoRltInfoR',
            raw_file=raw_name, raw_sha256=expected, retrieved_at='2026-10-26',
            collection='office-documents-20261026', office_topic='documents',
            scope='제2조의 행정기관 공통 절차. 기관별 담당자·사무전결 규칙·시스템 메뉴·고정 처리시간·실제 서식 파일은 별도 확인. 과거·미래 판본은 별도 검토.',
            units=[dict(loc=match[1] + ' 전체', text=text.strip())],
        ))
        (base / 'excerpts').mkdir(exist_ok=True)
        (base / 'excerpts' / filename).write_bytes(excerpt)
    (base / 'manifest.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    return rows


if __name__ == '__main__':
    print(json.dumps(dict(articles=len(build()), network_used=False), ensure_ascii=False))
