"""Collect the national civil-service conduct and discipline guideline (예규).

The PDF is downloaded once from law.go.kr, checked to be the expected
issue, kept with its SHA-256, and split into chapter > section > item units
with page numbers. Archived files are never replaced; a newer issue needs a
new collection directory and review.
"""
from pathlib import Path
from datetime import datetime,timezone
from urllib.request import Request,urlopen
from urllib.parse import urlsplit,unquote
import hashlib,io,json,re

COLLECTION='service-guidelines-20261029'
BASE=Path(__file__).resolve().parents[1]/'reference_data'/COLLECTION
SOURCE=dict(title='국가공무원 복무·징계 관련 예규',publication='인사혁신처예규 제225호',effective_date='2026-10-01',
            issuer='인사혁신처',institution='국가공무원',kind='업무지침',
            page_url='https://www.law.go.kr/admRulLsInfoP.do?admRulSeq=2100000285756',
            download_url='https://www.law.go.kr/LSW/flDownload.do?flSeq=170001959')
NAMES=('국가공무원 선서 및 복종의 의무','근무사항의 관리','근무일과 공휴일','유연근무제','당직 및 비상근무','출장',
       '공무국외출장 등','휴가','영리업무 금지 및 겸직허가','외부강의','공무원증','징계')
RUNNING=re.compile(r'^\s*(?:\d{1,3}|제\s*\d+\s*장\s*/\s*.+|국가공무원 복무·징계 관련 예규)\s*$')
CHAPTER=re.compile(r'^제\s*(\d+)\s*장\s*/\s*(.+)$')
SECTION=re.compile(r'^\s*(\d{1,2})\.\s+(\S.{0,24})$')
ITEM=re.compile(r'^\s*([가-하])\.\s+(\S.{0,24})$')
# A heading is a short title; a numbered sentence inside the body is not.
SENTENCE=re.compile(r'[,.]|(?:하게|하여|경우|때|하고|하며|및|의|을|를|에|로|으로|하는|되는|한|된|함|임|음)$')


def heading(match):
    return match and '·····' not in match.string and not SENTENCE.search(match[2].strip())


def fetch():
    request=Request(SOURCE['download_url'],headers={'User-Agent':'SeomuAssistant-public-source-review/1.0'})
    with urlopen(request,timeout=120) as response:
        if urlsplit(response.url).hostname not in {'law.go.kr','www.law.go.kr'}:raise ValueError('Unexpected redirect')
        name=unquote(response.headers.get('Content-Disposition',''))
        raw=response.read(30*1024*1024+1)
    if len(raw)>30*1024*1024 or not raw.startswith(b'%PDF'):raise ValueError('Unexpected download')
    if '제225호' not in name:raise ValueError('Unexpected guideline issue: '+name)
    return raw


def sections(raw):
    """Split body pages into units; each page's chapter comes from the printed table of contents."""
    from pypdf import PdfReader
    texts=[page.extract_text() or '' for page in PdfReader(io.BytesIO(raw)).pages]
    # Even pages carry no chapter header, so the printed page number decides the chapter.
    toc=[(int(start),f'제{number}장 {NAMES[int(number)-1]}') for number,_,start in
         re.findall(r'제\s*(\d+)\s*장\s+([^·\n]+?)\s*·+\s*(\d+)','\n'.join(texts[:12]))]
    if [title for _,title in toc]!=[f'제{i}장 {name}' for i,name in enumerate(NAMES,1)]:raise ValueError('Table of contents differs')
    units=[];chapter=section=item=None;started=False;lines=[];pages=[]
    def flush():
        text='\n'.join(lines).strip()
        if started and chapter and len(text)>=40:
            units.append(dict(chapter=chapter,section=section,item=item,pages=sorted(set(pages)),text=text))
        lines.clear();pages.clear()
    for number,text in enumerate(texts,1):
        page_lines=text.splitlines()
        printed=int(page_lines[0]) if page_lines and page_lines[0].strip().isdigit() else None
        if printed is not None and '·····' not in text:
            name=next((title for start,title in reversed(toc) if start<=printed),None)
            if name and name!=chapter:flush();chapter,section,item=name,None,None
            started=started or name is not None
        for line in page_lines:
            if not started or RUNNING.match(line) or re.fullmatch(r'\s*제\s*장\s*',line):continue
            match=SECTION.match(line)
            if heading(match):
                flush();section,item=f'{match[1]}. {match[2].strip()}',None
            else:
                match=ITEM.match(line)
                if heading(match):flush();item=f'{match[1]}. {re.sub(r"\s+"," ",match[2]).strip()}'
            lines.append(line.rstrip());pages.append(number)
    flush()
    for index,unit in enumerate(units,1):
        unit['id']=f'guideline-{index:04d}';unit['sha256']=hashlib.sha256(unit['text'].encode('utf-8')).hexdigest()
    return units


def keep(path,content):
    if path.exists() and path.read_bytes()!=content:raise ValueError('Refusing to replace archived source: '+path.name)
    path.write_bytes(content)


def collect():
    BASE.mkdir(parents=True,exist_ok=True)
    raw=(BASE/'guideline.pdf').read_bytes() if (BASE/'guideline.pdf').exists() else fetch()
    keep(BASE/'guideline.pdf',raw)
    data=json.dumps(sections(raw),ensure_ascii=False,indent=1).encode('utf-8')
    keep(BASE/'sections.json',data)
    manifest=dict(SOURCE,collection=COLLECTION,raw_file='guideline.pdf',raw_sha256=hashlib.sha256(raw).hexdigest(),
                  sections_file='sections.json',sections_sha256=hashlib.sha256(data).hexdigest(),
                  retrieved_at=datetime.now(timezone.utc).isoformat(),
                  scope='국가공무원 복무 실무 기준 · 법령 조문이 아님 · 지방공무원은 행정안전부 지침 확인')
    if not (BASE/'manifest.json').exists():
        (BASE/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return manifest


if __name__=='__main__':
    print(json.dumps(collect(),ensure_ascii=False,indent=2))
