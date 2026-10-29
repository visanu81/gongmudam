"""Hash-checked national conduct and discipline guideline (인사혁신처 예규).

The guideline is practical guidance below the decree: it supplements an
article with the operating standard, and answers a conduct question that no
article covers directly, labeled as guidance. It applies to national, fire
and police officers; local officers follow the Ministry of the Interior's
own guideline, so it is not used for them.
"""
from pathlib import Path
from urllib.parse import urlsplit
from functools import lru_cache
import hashlib,json,re
from .search import BM25

COLLECTION='service-guidelines-20261029'
BASE=Path(__file__).resolve().parents[1]/'reference_data'/COLLECTION
LIBRARY='service-guidelines'
SOURCE_TITLE='국가공무원 복무·징계 관련 예규'
NOTICE='등록된 법령 조문에서 직접 근거를 찾지 못해 인사혁신처 「국가공무원 복무·징계 관련 예규」의 실무 기준으로 안내해요. 소속 기관의 별도 기준을 함께 확인하세요.'
CHAPTERS=(
 ('제12장',r'징계|견책|감봉|정직|강등|파면|해임|징계부가금|징계위원회'),
 ('제10장',r'외부강의|강의료|강연료|외부강연'),
 ('제11장',r'공무원증'),
 ('제7장',r'국외출장|공무국외|해외출장|국외여행'),
 ('제4장',r'유연근무|재택근무|원격근무|시차출퇴근|근무시간선택|집약근무|탄력근무'),
 ('제5장',r'당직|비상근무|비상소집'),
 ('제9장',r'겸직|영리업무|영리행위'),
 ('제8장',r'휴가|연가|병가|공가|반일|반차|육아시간|모성보호|출산|경조사|가족돌봄|난임|대체휴무'),
 ('제2장',r'지각|조퇴|외출|근무상황'),
 ('제3장',r'근무시간|근무일|공휴일|토요일|점심시간|시간외근무|초과근무'),
 ('제6장',r'출장'),
 ('제1장',r'선서|복종'),
)
# Long sections are read in windows that keep a numbered item together.
WINDOW=1600


@lru_cache(maxsize=1)
def catalog():
    """(manifest, units) after verifying both stored files; empty when anything differs."""
    try:
        manifest=json.loads((BASE/'manifest.json').read_text(encoding='utf-8'))
        for url in (manifest['page_url'],manifest['download_url']):
            if urlsplit(url).scheme!='https' or urlsplit(url).hostname not in {'law.go.kr','www.law.go.kr'}:return None,()
        if hashlib.sha256((BASE/manifest['raw_file']).read_bytes()).hexdigest()!=manifest['raw_sha256']:return None,()
        data=(BASE/manifest['sections_file']).read_bytes()
        if hashlib.sha256(data).hexdigest()!=manifest['sections_sha256']:return None,()
        return manifest,tuple(_windows(json.loads(data)))
    except (OSError,KeyError,TypeError,ValueError):return None,()


def _windows(sections):
    for section in sections:
        blocks=re.split(r'\n(?=\s*\(\d+\)\s)',section['text']);chunk=''
        for block in blocks:
            if chunk and len(chunk)+len(block)>WINDOW:
                yield _unit(section,chunk);chunk=''
            chunk=(chunk+'\n'+block).strip()
            while len(chunk)>WINDOW*2:
                yield _unit(section,chunk[:WINDOW]);chunk=chunk[WINDOW:]
        if chunk:yield _unit(section,chunk)


def _unit(section,text):
    path=' > '.join(p for p in (section['chapter'],section['section'],section['item']) if p)
    return dict(path=path,chapter=section['chapter'],pages=section['pages'],text=text,
                sha256=hashlib.sha256(text.encode('utf-8')).hexdigest())


def metadata(sha):
    manifest,units=catalog()
    unit=next((u for u in units if u['sha256']==sha),None)
    return _official(manifest,unit) if unit else None


def _official(manifest,unit):
    return dict(manifest,article=unit['path'],sha256=unit['sha256'],pages=unit['pages'])


def chapter(query):
    q=re.sub(r'\s+','',query)
    return next((name for name,pattern in CHAPTERS if re.search(pattern,q)),None)


def applies(query):
    from . import service_rules
    found=service_rules.status(query)
    # The national guideline does not govern a province's own officials.
    return found!='local' and not (found is None and service_rules.region(query))


def search(query,k=2):
    """Top guideline windows within the chapter the question is about."""
    manifest,units=catalog();name=chapter(query)
    if not manifest or not name or not applies(query):return []
    scoped=[u for u in units if u['chapter'].startswith(name+' ')]
    if not scoped:return []
    from . import knowledge_relevance as relevance
    terms=relevance.expanded_query(query)
    # A matching section title outweighs scattered words in a long section body.
    titles=BM25([u['path'].split(' > ',1)[-1] for u in scoped]).scores(terms)
    bodies=BM25([u['text'] for u in scoped]).scores(terms)
    combined=[2*t+b for t,b in zip(titles,bodies)]
    ranked=[(i,combined[i]) for i in sorted(range(len(scoped)),key=lambda i:combined[i],reverse=True)[:k] if combined[i]>=4.0]
    hits=[]
    for index,score in ranked:
        unit=scoped[index];page=f"p.{unit['pages'][0]}" if unit['pages'] else ''
        hits.append(dict(id=f"{LIBRARY}:{unit['sha256'][:16]}",text=unit['text'],loc=' · '.join(p for p in (page,unit['path']) if p),
                         source_id=f"{LIBRARY}:{unit['chapter']}",title=f"{manifest['title']} {unit['chapter']}",kind=manifest['kind'],
                         institution=manifest['institution'],effective_date=manifest['effective_date'],sha256=unit['sha256'],
                         limited=False,library_id=LIBRARY,file_id=unit['sha256'][:16],official=_official(manifest,unit),score=round(score,2)))
    return hits
