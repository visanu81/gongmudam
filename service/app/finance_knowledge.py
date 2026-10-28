"""Verified finance source sections; scope and coverage, never payment decisions."""
from pathlib import Path
from datetime import date
from urllib.parse import urlsplit
import hashlib
import json
import re
from fastapi import APIRouter,HTTPException
from fastapi.responses import FileResponse

BASE=Path(__file__).resolve().parents[1]/'reference_data/finance-20261025'
HOSTS={'mpb.go.kr','www.mpb.go.kr','law.go.kr','www.law.go.kr','mois.go.kr','www.mois.go.kr'}
router=APIRouter(prefix='/api/finance-sources',tags=['예산·회계 원문'])


def asset(folder,name):
    if not isinstance(name,str) or Path(name).name!=name or '\\' in name or ':' in name:raise ValueError('Invalid finance asset')
    return folder/name


def metadata(sha):
    try:
        rows=json.loads((BASE/'manifest.json').read_text(encoding='utf-8'))
        row=next((r for r in rows if r['sha256']==sha),None)
        if not row:return None
        url=urlsplit(row['source_url'])
        if url.scheme!='https' or url.hostname not in HOSTS:return None
        for folder,name,digest in (('raw',row['raw_file'],row['raw_sha256']),('excerpts',row['filename'],sha)):
            if hashlib.sha256(asset(BASE/folder,name).read_bytes()).hexdigest()!=digest:return None
        return row
    except (OSError,ValueError,KeyError,TypeError):return None


@router.get('/{sha}/original')
def original(sha:str):
    row=metadata(sha)
    if not row:raise HTTPException(404,'등록한 예산·회계 원문의 해시를 확인하지 못했습니다.')
    path=asset(BASE/'raw',row['raw_file'])
    return FileResponse(path,media_type='application/pdf' if path.suffix=='.pdf' else 'application/octet-stream',
        filename=path.name,content_disposition_type='inline' if path.suffix=='.pdf' else 'attachment',headers={'Cache-Control':'no-store'})


def topics(query):
    q=re.sub(r'\s+','',query)
    from . import knowledge_relevance as rel
    context=rel.evidence_context(query)
    if context=='privacy':return set()
    # The existing purchase-card points/disclosure and travel rules remain separate.
    if any(t in q for t in ('포인트','적립','공개','홈페이지','공시','겸직','영리업무','휴가','연가','병가','견적','수의계약','검수','검사조서')):return set()
    if context not in {'overtime_meal','meeting_meal'} and any(t in q for t in ('출장','여비')):return set()
    result={context} if context in {'overtime_meal','meeting_meal'} else set()
    if any(t in q for t in ('강사료','강사수당','강연료','초빙강사','외래강사')):result.add('lecturer')
    if any(t in q for t in ('원고료','원고수당','원고작성사례금')):result.add('manuscript')
    if any(t in q for t in ('정부구매카드','지방자치단체구매카드','법인카드','업무용카드','카드증빙','카드영수증','카드사용')):result.add('card')
    if rel.is_budget_question(query) or any(t in q for t in ('예산집행','집행기준','무슨비목','어느비목')):
        result.update(rel.budget_topics(query))
    return result


def scope(query):
    q=re.sub(r'\s+','',query)
    if any(t in q for t in ('교육청','학교회계','교육비특별회계','공기업','공공기관','공기업특별회계')):return 'unsupported'
    if '소방' in q and not any(t in q for t in ('국가기관','국가회계','국가예산','중앙부처','지방자치단체','지자체','시청','군청','구청')):return None
    national=any(t in q for t in ('국가기관','국가회계','국가예산','중앙부처','국가공무원','국가직'))
    local=any(t in q for t in ('지방자치단체','지방공무원','지방직','지자체','시청','군청','구청','지방의회'))
    if national and local:return 'mixed'
    if national:return 'national_government'
    if local:return 'local_government'
    return None


def documents(query,docs,today):
    """None preserves legacy retrieval when this pack has no matching subject."""
    wanted=topics(query)
    matching=[d for d in docs if set((d.get('official') or {}).get('finance_topics',[]))&wanted]
    if not matching:return None
    q=re.sub(r'\s+','',query)
    if wanted&{'overtime_meal','meeting_meal'} and any(t in q for t in ('출장','여비')) and (
            any(t in q for t in ('각각','비교','둘다')) or re.search(r'출장식비(?:와|과|및)',q)):
        return [],'출장 식비와 업무 집행 식비는 적용 기준이 다릅니다. 질문을 나누어 각각의 근거를 확인해 주세요.'
    target=scope(query)
    if target=='unsupported':return [],'교육청·공공기관 등 해당 회계에 맞는 별도 집행기준이 필요합니다.'
    if target in {None,'mixed'}:return [],'국가기관인지 지방자치단체인지 알려주세요. 두 회계의 집행기준을 섞지 않고 확인하겠습니다.'
    years={int(y) for y in re.findall(r'(?<!\d)(20\d{2})(?!\d)(?!\s*(?:만|천|억)?(?:원|명|건|개))',query)} or {today.year}
    requested_dates=[]
    for y,m,d in re.findall(r'(20\d{2})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})(?:일)?',query):
        try:requested_dates.append(date(int(y),int(m),int(d)).isoformat())
        except ValueError:return [],'질문한 날짜를 확인해 주세요. 적용 시점에 맞는 판본을 찾아야 합니다.'
    valid=[]
    for d in matching:
        info=d['official']
        if metadata(d['sha256'])!=info:continue
        if info['finance_scope']!=target or not d['enabled'] or not d['current']:continue
        if d.get('effective_date') and d['effective_date']>today.isoformat():continue
        if d.get('effective_date') and any(day<d['effective_date'] for day in requested_dates):continue
        if not years<=set(info['fiscal_years']):continue
        valid.append(d)
    return valid,('' if valid else '질문한 기관·회계연도에 적용할 확인된 예산 집행 원문이 없습니다. 해당 판본을 추가해야 합니다.')


def select(query,hits):
    needed=topics(query);selected=[]
    # A narrow FAQ example must not replace the main fee criteria. Include it
    # additionally only when the question asks about internal staff/examples.
    fee_main=[h for h in hits if (h.get('official') or {}).get('id')=='finance-national-2026-lecturers']
    if 'lecturer' in needed and fee_main:
        selected.append(max(fee_main,key=lambda h:h['score']));needed.remove('lecturer')
        if any(word in query for word in ('직원','내부','인재개발원','질의','사례')):
            faq=next((h for h in hits if (h.get('official') or {}).get('id')=='finance-national-2026-fee-faq'),None)
            if faq:selected.append(faq)
    for hit in sorted(hits,key=lambda h:h['score'],reverse=True):
        covered=set((hit.get('official') or {}).get('finance_topics',[]))&needed
        if not covered:continue
        selected.append(hit);needed-=covered
        if not needed:break
    if needed:return [],'질문한 항목 전체의 직접 근거가 부족합니다. 관련 집행기준·기관 지급기준을 더 확인해야 합니다.'
    return selected,''
