"""Hash-checked pay guidelines (인사혁신처 공무원보수 등의 업무지침, 행정안전부 지방공무원보수업무 등 처리지침).

The guidelines are the operating standard below the pay and allowance
decrees. An answer keeps the decree article as its evidence; the matching
guideline page is shown beside it as practice. The guideline follows the
regulation the answer used: national pay rules read the 인사혁신처 guideline,
local ones the 행정안전부 guideline.
"""
from pathlib import Path
from urllib.parse import urlsplit
from functools import lru_cache
import hashlib,json,re
from .search import BM25

COLLECTION='pay-guidelines-20261031'
BASE=Path(__file__).resolve().parents[1]/'reference_data'/COLLECTION
LIBRARY='pay-guidelines'
# Chapter number by guideline and question area.
CHAPTERS={'national':{'pay':1,'allowance':7,'performance':8,'welfare':11},'local':{'pay':1,'allowance':5,'performance':6}}
MIN_SCORE=8.0
QUOTE=900
# The guidelines have no section on these; a page that merely mentions the word is not practice.
NO_PRACTICE={'pay_payday','pay_table'}
GUIDELINE={'national_pay':'national','national_allowance':'national','welfare':'national','local_pay':'local','local_allowance':'local'}
UNREADABLE=re.compile('[-]+')


def readable(text):
    """Equation fonts in the official PDFs carry private-use glyphs with no character
    mapping (e.g. the 6/12 fraction on 226 p.76); no PDF reader recovers them. Say so
    instead of showing broken symbols. The stored, hash-checked text is unchanged."""
    return UNREADABLE.sub('[수식·기호: 원문 확인 필요]', text)


@lru_cache(maxsize=1)
def catalog():
    """{key: (manifest row, pages)} for every guideline whose stored files still match."""
    try:rows=json.loads((BASE/'manifest.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):return {}
    verified={}
    for row in rows:
        try:
            if any(urlsplit(row[k]).scheme!='https' or urlsplit(row[k]).hostname not in {'law.go.kr','www.law.go.kr'} for k in ('page_url','download_url')):continue
            if row.get('collection')!=COLLECTION:continue
            if hashlib.sha256((BASE/row['raw_file']).read_bytes()).hexdigest()!=row['raw_sha256']:continue
            data=(BASE/row['pages_file']).read_bytes()
            if hashlib.sha256(data).hexdigest()!=row['pages_sha256']:continue
            pages=tuple(p for p in json.loads(data) if hashlib.sha256(p['text'].encode('utf-8')).hexdigest()==p['sha256'])
            verified[row['key']]=(row,pages)
        except (OSError,KeyError,TypeError,ValueError):continue
    return verified


def metadata(sha):
    for row,pages in catalog().values():
        page=next((p for p in pages if p['sha256']==sha),None)
        if page:return _official(row,page)
    return None


def _official(row,page):
    path=' > '.join(p for p in (page['chapter'],page['section']) if p)
    return dict({k:row[k] for k in ('title','publication','effective_date','issuer','institution','kind','page_url','download_url')},
                article=path,sha256=page['sha256'],pages=[page['page']])


def _area(topic):
    if topic=='allowance_performance':return 'performance'
    return next((area for area in ('pay','allowance','welfare') if topic.startswith(area)),None)


def search(query,topic,law):
    """The best page of the guideline that goes with the regulation the answer used."""
    key=GUIDELINE.get(law);area=_area(topic or '')
    if not key or not area or topic in NO_PRACTICE or key not in catalog():return []
    number=CHAPTERS[key].get(area)
    row,pages=catalog()[key]
    scoped=[p for p in pages if number and re.match(rf'제\s*{number}\s*장',p['chapter'])]
    if not scoped:return []
    from . import knowledge_intent,knowledge_relevance as relevance
    label,words=knowledge_intent.TOPICS.get(topic,('',('',)))
    # Only pages that name the subject itself; a nearby topic on the same page is not practice for it.
    anchor=re.sub(r'\s+','',words[0])
    terms=relevance.expanded_query(query+' '+label+' '+label)
    # Scored across the whole chapter so the subject word keeps its weight.
    scores=BM25([p['text'] for p in scoped]).scores(terms)
    named=[i for i,p in enumerate(scoped) if anchor in re.sub(r'\s+','',p['text'])]
    if not named:return []
    best=max(named,key=lambda i:scores[i])
    if scores[best]<MIN_SCORE:return []
    page=scoped[best];official=_official(row,page)
    # Show the page from the line that names the subject; the full page stays as text.
    lines=page['text'].splitlines()
    start=next((i for i,line in enumerate(lines) if anchor in re.sub(r'\s+','',line)),0)
    quote=readable('\n'.join(lines[start:])[:QUOTE])
    return [dict(id=f"{LIBRARY}:{page['sha256'][:16]}",text=readable(page['text']),quote=quote,loc=f"p.{page['page']} · {official['article']}",
                 source_id=f"{LIBRARY}:{key}",title=f"{row['title']} {page['chapter']}",kind=row['kind'],institution=row['institution'],
                 effective_date=row['effective_date'],sha256=page['sha256'],limited=False,library_id=LIBRARY,
                 file_id=page['sha256'][:16],official=official,score=round(scores[best],2))]
