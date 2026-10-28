"""Offline, hash-checked MPM explanations/FAQs; never substitutes for a law.

The immutable snapshots ship as reference data, independent of the chosen model
and of private business databases. Only official text is returned, not new prose
generated from a FAQ. Individual answers can predate the current law.
"""
from pathlib import Path
from urllib.parse import urlsplit
import hashlib,json,re
from fastapi import APIRouter,HTTPException
from fastapi.responses import FileResponse
from .search import BM25
from . import leave_situations

BASE=Path(__file__).resolve().parents[1]/'reference_data'
PACKS=('mpm-service-20261024','mpm-faq-20261024')
NOTICE='국가공무원 제도 설명·FAQ의 보관본입니다. 확인일은 수집일이며 답변의 개정일을 뜻하지 않아요. 실제 적용·일수·예외는 현행 법령과 기관 기준을 확인하세요.'
router=APIRouter(prefix='/api/service-guides',tags=['인사혁신처 제도 안내·FAQ'])
DOMAINS=(
 ('active','적극행정 징계면제',('적극행정','징계면제'),('proactDisEx',)),
 ('sidejob','영리업무·겸직',('겸직','영리업무','유튜브','유튜버','업무취급','취급제한','취업심사'),('BizService06',)),
 ('flex','유연근무',('유연근무','시차출퇴근','재택근무','원격근무','근무시간선택','집약근무'),('BizService10',)),
 ('holiday','공휴일',('공휴일','대체공휴일','임시공휴일'),('BizService02',)),
 ('duty','당직·비상근무',('당직','비상근무'),('BizService03',)),
 ('foreign','공무국외출장',('공무국외','국외출장','해외출장'),('BizService08',)),
 ('travel','국내출장',('출장','여비'),('BizService07',)),
 ('discipline','징계',('징계','견책','감봉','정직','강등','파면','해임'),('BizService04',)),
 ('charter','공무원헌장',('공무원헌장','공직가치'),('civilCharter',)),
 ('leave','휴가·복무',('휴가','연가','병가','공가','육아시간','모성보호','가족돌봄','휴무'),('BizService01',)),
)


def domain(query):
    q=re.sub(r'\s+','',query)
    if leave_situations.family_care(query):return DOMAINS[-1]
    return next((row for row in DOMAINS if any(t in q for t in row[2])),None)


def _catalog():
    pages=[];coverage=dict(guide_pages=0,faq_questions=0);problems=[];checked={}
    for pack in PACKS:
        root=BASE/pack;manifest=root/'manifest.json'
        try:
            data=json.loads(manifest.read_text(encoding='utf-8'))
            for row in data['pages']:
                if not row.get('units'):continue
                url=urlsplit(row['source_url'])
                if url.scheme!='https' or url.hostname not in {'www.mpm.go.kr','mpm.go.kr'} or not url.path.startswith('/mpm/info/'):
                    raise ValueError('Unexpected official URL')
                if not re.fullmatch(r'[A-Za-z0-9_-]+',row['id']):raise ValueError('Invalid source ID')
                for field,sha in (('raw_file','raw_sha256'),('text_file','sha256')):
                    path=root/row[field]
                    if path.resolve().parent!=root.resolve() or path.is_symlink():raise ValueError('Invalid asset path')
                    if path not in checked:checked[path]=hashlib.sha256(path.read_bytes()).hexdigest()
                    if checked[path]!=row[sha]:raise ValueError('Source hash differs: '+row['id'])
                text=(root/row['text_file']).read_text(encoding='utf-8')
                if any(u['text'] not in text for u in row['units']):raise ValueError('Index differs from stored text')
                pages.append(row|dict(_root=root,_text=text))
                coverage['faq_questions' if row['reference_kind']=='official_faq' else 'guide_pages']+=1
        except (OSError,ValueError,KeyError,TypeError) as error:
            # Reject an incomplete pack as a whole, preserving unrelated good packs.
            pages=[p for p in pages if p['_root']!=root]
            coverage['faq_questions' if 'faq' in pack else 'guide_pages']=0
            problems.append(pack+': 보관 자료의 무결성을 확인하지 못했습니다 ('+type(error).__name__+').')
    return pages,coverage,problems


def _public(row):
    return {k:v for k,v in row.items() if not k.startswith('_') and k not in ('units','answer','question','raw_file','text_file')}


@router.get('')
def catalog():
    pages,coverage,problems=_catalog()
    return dict(sources=[_public(p)|dict(snapshot_url=f"/api/service-guides/{p['id']}/original") for p in pages],coverage=coverage,problems=problems,notice=NOTICE)


@router.get('/{key}/original')
def original(key:str):
    pages,_,_=_catalog();row=next((r for r in pages if r['id']==key),None)
    if row is None:raise HTTPException(404,'원문 사본이 없거나 해시 확인을 통과하지 못했습니다.')
    return FileResponse(row['_root']/row['text_file'],media_type='text/plain; charset=utf-8',
                        filename=row['text_file'],content_disposition_type='inline',headers={'Cache-Control':'no-store'})


def retrieve(query,library_id=None):
    pages,coverage,problems=_catalog()
    result=dict(evidence=[],coverage=coverage,notice=NOTICE,problems=problems)
    # Explicit library selection remains an exclusive scope, including offline guides.
    if library_id:return result
    selected=domain(query)
    if selected is None:return result
    # MPM guidance is not silently applied to a different employment framework.
    q=re.sub(r'\s+','',query)
    employee_q=re.sub(r'(?:담임)?교사(?:와의|와|상담)','',q)
    if any(t in employee_q for t in ('지방공무원','지방직','지자체공무원','공무직','교원','교사','공공기관직원','회사원','민간기업','사기업')):return result
    family=leave_situations.family_care(query)
    search=query+(' 가족돌봄휴가 질병 돌봄' if family else '')
    # FAQ headings carry purpose. A mention in an unrelated answer is insufficient.
    candidates=[]
    focus=next((t for t in ('가족돌봄','연가','병가','공가','육아시간','출산휴가','모성보호','임신검진','경조사') if t in q),None)
    if family:focus='가족돌봄'
    for row in pages:
        faq=row['reference_kind']=='official_faq'
        if faq:
            heading=re.sub(r'\s+','',row['title'])
            if family and '가족돌봄' not in heading:continue
            if not family and not any(t in heading for t in selected[2]):continue
            if selected[0]=='leave' and focus and focus not in heading:continue
            units=row['units']
        else:
            if row['id'] not in selected[3]:continue
            # Combine adjacent blocks in their section, retaining the original
            # complete source substring instead of detached table cell fragments.
            units=[];groups=[]
            for u in row['units']:
                if groups and groups[-1][0]==u['loc']:groups[-1][1].append(u)
                else:groups.append((u['loc'],[u]))
            for loc,items in groups:
                if focus:
                    items=[u for u in items if focus in re.sub(r'\s+','',loc+' '+u['text'])]
                for u in items:
                    if len(u['text'])>25:units.append(u)
        for u in units:
            if len(u['text'])<20:continue
            candidates.append((row,u))
    if not candidates:return result
    bm=BM25([r['title']+' '+u['loc']+' '+u['text'] for r,u in candidates])
    ranked=bm.top(search,k=len(candidates),min_score=0)
    seen=set();hits=[]
    for index,score in ranked:
        row,u=candidates[index]
        if (row['id'],u['text']) in seen:continue
        # A maximum of two snippets per page prevents one guide crowding out FAQs.
        if sum(h['id']==row['id'] for h in hits)>=2:continue
        seen.add((row['id'],u['text']))
        hits.append(dict(id=row['id'],title=row['title'],reference_kind=row['reference_kind'],quote=u['text'],loc=u['loc'],
                         sha256=row['sha256'],source_url=row['source_url'],snapshot_url=f"/api/service-guides/{row['id']}/original",
                         retrieved_at=row['retrieved_at'],scope=row['scope']))
        if len(hits)==3:break
    result['evidence']=hits
    return result
