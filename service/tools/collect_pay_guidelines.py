"""Collect the national and local pay guidelines (보수 업무지침) page by page.

Each PDF is downloaded once from law.go.kr, checked to be the expected issue
and kept with its SHA-256. Every body page is stored with its chapter (from
the running page header) and the nearest Roman-numeral section. Archived
files are never replaced; a newer issue needs a new collection and review.
"""
from pathlib import Path
from datetime import datetime,timezone
from urllib.request import Request,urlopen
from urllib.parse import urlsplit,unquote
import hashlib,io,json,re,sys

COLLECTION='pay-guidelines-20261031'
BASE=Path(__file__).resolve().parents[1]/'reference_data'/COLLECTION
SOURCES={
 'national':dict(title='공무원보수 등의 업무지침',publication='인사혁신처예규 제226호',effective_date='2026-10-01',
  issuer='인사혁신처',institution='국가공무원',kind='업무지침',issue='제226호',raw_file='national-226.pdf',pages_file='national-226.pages.json',
  page_url='https://www.law.go.kr/LSW/admRulInfoP.do?admRulSeq=2100000285788',
  download_url='https://www.law.go.kr/LSW/flDownload.do?flSeq=170002251'),
 'local':dict(title='지방공무원보수업무 등 처리지침',publication='행정안전부예규 제389호',effective_date='2026-10-01',
  issuer='행정안전부',institution='지방공무원',kind='업무지침',issue='제389호',raw_file='local-389.pdf',pages_file='local-389.pages.json',
  page_url='https://www.law.go.kr/LSW/admRulInfoP.do?admRulSeq=2100000285694',
  download_url='https://www.law.go.kr/LSW/flDownload.do?flSeq=169846039'),
}
HEADER=re.compile(r'^\s*(제\s*\d+\s*장\s*[^●\d]+?)\s*(?:●\s*\d+\s*●|\d+)\s*$')
RUNNING=re.compile(r'^\s*(?:●\s*\d+\s*●\s*|\d+\s+)?(?:공무원보수 등의 업무지침|지방공무원보수업무 등 처리지침)\s*$')
ROMAN=re.compile(r'^\s*([ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ]+)\s*\.?\s*(\S.{0,40})$')
MAX_BYTES=30*1024*1024


def fetch(source):
    request=Request(source['download_url'],headers={'User-Agent':'SeomuAssistant-public-source-review/1.0'})
    with urlopen(request,timeout=180) as response:
        if urlsplit(response.url).hostname not in {'law.go.kr','www.law.go.kr'}:raise ValueError('Unexpected redirect')
        name=unquote(response.headers.get('Content-Disposition',''))
        raw=response.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES or not raw.startswith(b'%PDF'):raise ValueError('Unexpected download')
    return raw,name


def pages(raw,source):
    """Body pages with chapter and section; table-of-contents pages are left out."""
    from pypdf import PdfReader
    texts=[page.extract_text() or '' for page in PdfReader(io.BytesIO(raw)).pages]
    if not any(source['issue'] in text or source['publication'].replace(' ','') in text.replace(' ','') for text in texts[:12]):
        raise ValueError('Unexpected guideline issue: '+source['title'])
    units=[];chapter=section=None
    for number,text in enumerate(texts,1):
        lines=[line for line in text.splitlines() if line.strip()]
        if lines and HEADER.match(lines[0]):
            name=re.sub(r'\s+',' ',HEADER.match(lines[0])[1]).strip()
            if name!=chapter:chapter,section=name,None
            lines=lines[1:]
        elif lines and RUNNING.match(lines[0]):lines=lines[1:]
        if not chapter or text.count('·····')>=3:continue
        for line in lines:
            match=ROMAN.match(line)
            if match:section=f'{match[1]}. {match[2].strip()}'
        body='\n'.join(line.rstrip() for line in lines).strip()
        if len(body)<80:continue
        units.append(dict(page=number,chapter=chapter,section=section,text=body,
                          sha256=hashlib.sha256(body.encode('utf-8')).hexdigest()))
    return units


def keep(path,content):
    if path.exists() and path.read_bytes()!=content:raise ValueError('Refusing to replace archived source: '+path.name)
    path.write_bytes(content)


def collect(keys=None):
    BASE.mkdir(parents=True,exist_ok=True);manifest=[]
    for key,source in SOURCES.items():
        if keys and key not in keys:continue
        raw,name=fetch(source)
        units=pages(raw,source)
        data=json.dumps(units,ensure_ascii=False,indent=1).encode('utf-8')
        keep(BASE/source['raw_file'],raw);keep(BASE/source['pages_file'],data)
        manifest.append(dict({k:v for k,v in source.items() if k!='issue'},key=key,collection=COLLECTION,download_name=name,
            retrieved_at=datetime.now(timezone.utc).isoformat(),raw_sha256=hashlib.sha256(raw).hexdigest(),
            pages_sha256=hashlib.sha256(data).hexdigest(),pages=len(units),
            chapters=sorted({u['chapter'] for u in units},key=lambda c:int(re.search(r'\d+',c)[0]))))
    (BASE/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return manifest


if __name__=='__main__':
    for row in collect(set(sys.argv[1:]) or None):
        print(row['key'],row['pages'],row['chapters'])
