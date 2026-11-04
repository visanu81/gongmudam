"""Collect the 2026 pay tables and 정근수당 rates from law.go.kr annex PDFs.

The decree articles (collected in service-rules-20261029) leave annexes out; the
amounts live in 별표 PDFs. Each PDF is stored with SHA-256 next to the table read
from it, so the calculator can show which annex a number came from. Archived files
are never replaced; a changed annex must be reviewed as a new collection.

usage (from service/): python -X utf8 tools/collect_pay_tables.py
"""
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
import hashlib, io, json, re, sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.pay_tables import COLLECTION, BASE, PARSERS  # noqa: E402

PAGE = 'https://www.law.go.kr/LSW/lsBylInfoPLinkR.do?lsiSeq={lsi}&bylNo={no}&bylBrNo=00&bylCls=BE&bylEfYd=&bylEfYdYn=Y'
FILE = 'https://www.law.go.kr/LSW/flDownload.do?flSeq={fl}'
# flSeq of the PDF shown on each annex page on 2026-11-03.
ANNEXES = [
    dict(id='salary-general', kind='salary', law='공무원보수규정', lsi=290321, no='0003', fl=169560643,
         title='[별표 3] 일반직공무원과 일반직에 준하는 특정직 및 별정직 공무원 등의 봉급표', revised='2026. 1. 2.',
         applies='국가 일반직, 지방 일반직(지방공무원 보수규정 제4조제3항 준용)'),
    dict(id='salary-police-fire', kind='salary', law='공무원보수규정', lsi=290321, no='0010', fl=169560697,
         title='[별표 10] 경찰공무원ㆍ소방공무원 및 의무경찰 등의 봉급표', revised='2026. 1. 2.', applies='경찰공무원, 소방공무원'),
    dict(id='longevity-national', kind='longevity', law='공무원수당 등에 관한 규정', lsi=290323, no='0002', fl=169637279,
         title='[별표 2] 정근수당 지급 구분표(제7조제1항 관련)', revised='2025. 1. 3.', applies='국가공무원'),
    dict(id='longevity-local', kind='longevity', law='지방공무원 수당 등에 관한 규정', lsi=289957, no='0002', fl=169315875,
         title='[별표 2] 정근수당 지급구분표(제6조제1항 관련)', revised='2025. 1. 3.', applies='지방공무원'),
    dict(id='family-national', kind='family', law='공무원수당 등에 관한 규정', lsi=290323, no='0005', fl=169637315,
         title='[별표 5] 가족수당 지급 구분표(제10조제1항 관련)', revised='2025. 1. 3.', applies='국가공무원'),
    dict(id='subsidy-national', kind='subsidy', law='공무원수당 등에 관한 규정', lsi=290323, no='0015', fl=169637483,
         title='[별표 15] 직급보조비 지급 구분표(제18조의6 관련)', revised='2026. 9. 29.', applies='국가공무원, 경찰공무원, 소방공무원'),
    dict(id='subsidy-local', kind='subsidy', law='지방공무원 수당 등에 관한 규정', lsi=289957, no='0014', fl=169316005,
         title='[별표 14] 직급보조비 지급구분표(제18조의6 관련)', revised='2026. 6. 23.', applies='지방공무원'),
]
# The local 가족수당 amounts are in the article, already collected and hashed with the service rules.
ARTICLES = [
    dict(id='family-local', kind='family', law='지방공무원 수당 등에 관한 규정', article='local_allowance-10',
         title='제10조(가족수당) 제1항', revised='2025. 1. 3.', applies='지방공무원'),
    dict(id='meal-national', kind='meal', law='공무원수당 등에 관한 규정', article='national_allowance-18',
         title='제18조(정액급식비)', revised='2026. 1. 2.', applies='국가공무원'),
    dict(id='meal-local', kind='meal', law='지방공무원 수당 등에 관한 규정', article='local_allowance-18',
         title='제18조(정액급식비)', revised='2026. 1. 2.', applies='지방공무원'),
]
RULES = BASE.parent / 'service-rules-20261029'
# The overtime rates are a table in the pay guidelines (already collected with hashes),
# 제7장 [별표2] 초과근무수당 지급단가; the pages holding it are stored as text.
GUIDES = [
    dict(id='overtime-national', kind='overtime', key='national', pages=(488, 489), law='공무원보수 등의 업무지침',
         title='제7장 [별표2] 초과근무수당 지급단가', applies='국가공무원, 경찰공무원, 소방공무원'),
    dict(id='overtime-local', kind='overtime', key='local', pages=(409,), law='지방공무원보수업무 등 처리지침',
         title='제5장 【별표2】 초과근무수당 지급단가', applies='지방공무원'),
    dict(id='honorary-national', kind='honorary', key='national', pages=(490, 494), law='공무원보수 등의 업무지침',
         title='제7장 [별표3] 대우공무원수당 조견표', applies='국가공무원(일반직), 경찰공무원, 소방공무원'),
    dict(id='honorary-local', kind='honorary', key='local', pages=(411,), law='지방공무원보수업무 등 처리지침',
         title='제5장 【별표3】 대우공무원수당 조견표', applies='지방공무원(일반직)'),
]
GUIDELINES = BASE.parent / 'pay-guidelines-20261031'


def fetch(url):
    with urlopen(Request(url, headers={'User-Agent': 'SeomuAssistant-public-source-review/1.0'}), timeout=60) as r:
        return r.read()


def main():
    import pypdf
    (BASE / 'raw').mkdir(parents=True, exist_ok=True)
    manifest, tables = [], {}
    for a in ANNEXES:
        data = fetch(FILE.format(fl=a['fl']))
        if not data.startswith(b'%PDF'):
            raise ValueError('Not a PDF: ' + a['id'])
        digest = hashlib.sha256(data).hexdigest()
        raw = BASE / 'raw' / f"{a['id']}.pdf"
        if raw.exists() and hashlib.sha256(raw.read_bytes()).hexdigest() != digest:
            raise ValueError('Annex changed since collection; review as a new collection: ' + a['id'])
        raw.write_bytes(data)
        text = '\n'.join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(data)).pages)
        if a['revised'].replace(' ', '') not in re.sub(r'\s', '', text):
            raise ValueError('Unexpected revision in ' + a['id'])
        tables[a['id']] = PARSERS[a['kind']](text)
        manifest.append({k: a[k] for k in ('id', 'kind', 'law', 'title', 'revised', 'applies')} | dict(
            source_url=PAGE.format(lsi=a['lsi'], no=a['no']), download_url=FILE.format(fl=a['fl']),
            raw_file=raw.name, sha256=digest, retrieved_at=datetime.now(timezone.utc).isoformat(timespec='seconds')))
    rules = {e['id']: e for e in json.loads((RULES / 'manifest.json').read_text(encoding='utf-8'))}
    for a in ARTICLES:
        entry = rules[a['article']]
        data = (RULES / 'excerpts' / entry['filename']).read_bytes()
        if hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise ValueError('Article changed since the service rules were collected: ' + a['article'])
        raw = BASE / 'raw' / f"{a['id']}.txt"
        raw.write_bytes(data)
        text = data.decode('utf-8')
        if a['revised'] not in text:
            raise ValueError('Unexpected revision in ' + a['id'])
        tables[a['id']] = PARSERS[a['kind']](text)
        manifest.append({k: a[k] for k in ('id', 'kind', 'law', 'title', 'revised', 'applies')} | dict(
            source_url=entry['source_url'], download_url=entry['download_url'], raw_file=raw.name, sha256=entry['sha256'],
            retrieved_at=entry['retrieved_at']))
    guides = {e['key']: e for e in json.loads((GUIDELINES / 'manifest.json').read_text(encoding='utf-8'))}
    for a in GUIDES:
        entry = guides[a['key']]
        pages_file = GUIDELINES / entry['pages_file']
        if hashlib.sha256(pages_file.read_bytes()).hexdigest() != entry['pages_sha256']:
            raise ValueError('Pay guideline pages changed: ' + a['key'])
        pages = [p for p in json.loads(pages_file.read_text(encoding='utf-8')) if p['page'] in a['pages']]
        if [p['page'] for p in pages] != list(a['pages']) or any(hashlib.sha256(p['text'].encode('utf-8')).hexdigest() != p['sha256'] for p in pages):
            raise ValueError('Pay guideline page mismatch: ' + a['id'])
        data = '\n'.join(p['text'] for p in pages).encode('utf-8')
        raw = BASE / 'raw' / f"{a['id']}.txt"
        raw.write_bytes(data)
        tables[a['id']] = PARSERS[a['kind']](data.decode('utf-8'))
        manifest.append({k: a[k] for k in ('id', 'kind', 'law', 'title', 'applies')} | dict(
            revised=entry['publication'], source_url=entry['page_url'], download_url=entry['download_url'], raw_file=raw.name,
            sha256=hashlib.sha256(data).hexdigest(), pages=list(a['pages']), retrieved_at=entry['retrieved_at']))
    (BASE / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding='utf-8')
    (BASE / 'tables.json').write_text(json.dumps(tables, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(dict(collection=COLLECTION, annexes=len(manifest)), ensure_ascii=False))


if __name__ == '__main__':
    main()
