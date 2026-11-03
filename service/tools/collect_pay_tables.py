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
from app.pay_tables import COLLECTION, BASE, parse_salary, parse_longevity  # noqa: E402

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
]


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
        tables[a['id']] = parse_salary(text) if a['kind'] == 'salary' else parse_longevity(text)
        manifest.append({k: a[k] for k in ('id', 'kind', 'law', 'title', 'revised', 'applies')} | dict(
            source_url=PAGE.format(lsi=a['lsi'], no=a['no']), download_url=FILE.format(fl=a['fl']),
            raw_file=raw.name, sha256=digest, retrieved_at=datetime.now(timezone.utc).isoformat(timespec='seconds')))
    (BASE / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding='utf-8')
    (BASE / 'tables.json').write_text(json.dumps(tables, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(dict(collection=COLLECTION, annexes=len(manifest)), ensure_ascii=False))


if __name__ == '__main__':
    main()
