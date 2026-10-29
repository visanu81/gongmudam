"""Hash-checked civil-service conduct regulations shipped with the app.

The four regulations (national, local, fire, police) answer conduct questions
without any registration in a private database, so the personal app and the
public site read the same articles. The status in the question selects the
regulation; fire and police special rules are read together with the national
regulation they apply mutatis mutandis. Retrieval still ranks the original text.
"""
from pathlib import Path
from urllib.parse import urlsplit
from functools import lru_cache
import hashlib,json,re

COLLECTION='service-rules-20261029'
BASE=Path(__file__).resolve().parents[1]/'reference_data'/COLLECTION
LIBRARY='service-rules'
STATUS=(
 # 소방청과 그 소속기관은 국가 소방이라 시·도 조례를 적용하지 않습니다.
 ('fire_national',r'소방청소속|국가소방|중앙소방학교|국립소방연구원|중앙119구조본부'),
 ('fire',r'소방'),
 ('police',r'경찰|순경|경장|경사|경위|경감|경정|총경|치안'),
 ('local',r'지방공무원|지방직|지자체|지방자치단체|시청|군청|구청|도청|읍사무소|면사무소|주민센터|행정복지센터'),
 ('national',r'국가공무원|국가직|국가기관|중앙부처|중앙행정기관|정부부처'),
)
# Regulations read for each status; the special rules come first. Without a
# status the existing local-first leave mapping still decides the evidence.
READS={'national':('national',),'local':('local',),'fire':('fire','national'),'fire_national':('fire','national'),
       'police':('police','national'),None:('local','national')}
# Bundled ordinances by region. They apply to the province's own officials and,
# through 소방공무원 복무규정 제11조, to its fire officers; a city or county has its own.
ORDINANCE={'gyeonggi':(r'경기도(?!교육)|경기소방','경기도 공무원 복무 조례')}
TITLES={'national':'국가공무원 복무규정','local':'지방공무원 복무규정','fire':'소방공무원 복무규정','police':'경찰공무원 복무규정',
        **{key:title for key,(_,title) in ORDINANCE.items()}}
_PUBLIC=('public_leave','public_health','public_blood')
_SPECIAL=('childcare','family_care','maternity','pregnancy_check','pregnancy_accompany','maternal_time',
          'miscarriage','fertility','women_health','disaster_leave','mental_leave','occasion')
# Direct article for an intent topic in each regulation. Fire and police fall
# back to the national regulation for topics their own decree does not cover.
ARTICLES={
 'national':{'annual':('제15조(',),'annual_use':('제16조(','제16조의2(','제16조의3(','제16조의4(','제17조('),'sick':('제18조(',),
             **{t:('제19조(',) for t in _PUBLIC},**{t:('제20조(',) for t in _SPECIAL},'leave_holiday':('제22조(',),
             'side_job':('제25조(','제26조('),'work_hours':('제9조(','제10조('),'overtime':('제11조(',),'duty':('제5조(',),
             'politics':('제27조(',),'dress':('제8조의2(',),'long_service':('제20조(',),'election_rest':('제6조의2(',)},
 'local':{'annual':('제7조(',),'annual_use':('제7조의3(','제7조의4(','제7조의10(','제7조의11('),'sick':('제7조의5(',),
          **{t:('제7조의6(',) for t in _PUBLIC},**{t:('제7조의7(',) for t in _SPECIAL},'leave_holiday':('제7조의8(',),
          'side_job':('제10조(','제11조('),'work_hours':('제2조(','제3조('),'overtime':('제4조(',),
          'duty':('제2조의2(','제2조의3(','제2조의4('),'politics':('제9조(',),'dress':('제1조의3(',),'election_rest':('제4조의3(',),
          # The decree leaves special leave it does not define to each ordinance.
          'long_service':('제7조의7(',),'region_leave':('제7조의7(',)},
 'fire':{**{t:('제8조의2(',) for t in _PUBLIC},'reward_leave':('제9조(',),'duty':('제5조(',),'travel_limit':('제4조(',),'shift':('제6조(',)},
 'police':{'reward_leave':('제18조(',),'duty':('제14조(',),'travel_limit':('제13조(',),'drinking':('제9조(',),'dress':('제5조(',)},
 'gyeonggi':{'long_service':('제14조(',),'region_leave':('제14조(',)},
}
# 시·도 소방의 장기재직휴가는 국가 기준이 아니라 조례로 정합니다(소방공무원 복무규정 제11조②).
FIRE_ORDINANCE=('long_service','region_leave')
SUBJECT=re.compile(r'장기재직|새내기|생일특별|휴가|연가|병가|공가|특별휴가|경조사|출산|육아시간|모성보호|난임|근무시간|시간외|초과근무|당직|비상근무|비상소집|'
                   r'겸직|영리|정치|복장|복제|지각|조퇴|외출|휴무|포상|국외여행|여행|교대|선서|비밀|친절|복무|토요일|공휴일|근무혁신|유연근무|파견|겸임')


def status(query):
    q=re.sub(r'\s+','',query)
    return next((key for key,pattern in STATUS if re.search(pattern,q)),None)


def region(query):
    q=re.sub(r'\s+','',query)
    return next((key for key,(pattern,_) in ORDINANCE.items() if re.search(pattern,q)),None)


def reads(query):
    """Regulations for the stated status; a known province's ordinance goes first."""
    found=status(query);place=region(query)
    if place and found in ('local','fire',None):
        return (place,)+READS[found if found else 'local']
    return READS[found]


def is_subject(query):
    return bool(SUBJECT.search(re.sub(r'\s+','',query)))


@lru_cache(maxsize=1)
def catalog():
    """Return verified rows; a row whose stored text or raw page differs is dropped."""
    try:rows=json.loads((BASE/'manifest.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):return ()
    verified=[]
    for row in rows:
        try:
            address=urlsplit(row['source_url'])
            if address.scheme!='https' or address.hostname not in {'law.go.kr','www.law.go.kr'} or row.get('collection')!=COLLECTION:continue
            excerpt=BASE/'excerpts'/row['filename'];raw=BASE/'raw'/row['raw_file']
            if excerpt.parent!=BASE/'excerpts' or raw.parent!=BASE/'raw':continue
            text=excerpt.read_bytes()
            if hashlib.sha256(text).hexdigest()!=row['sha256'] or hashlib.sha256(raw.read_bytes()).hexdigest()!=row['raw_sha256']:continue
            verified.append((row,text.decode('utf-8')))
        except (OSError,KeyError,TypeError,ValueError):continue
    return tuple(verified)


def article_key(official):
    """(regulation, article number) such as ('국가공무원 복무규정', '제18조')."""
    return (official.get('title'),official.get('article','').split('(')[0]) if official.get('title') in TITLES.values() else None


def metadata(sha):
    return next((row for row,_ in catalog() if row['sha256']==sha),None)


def document(row,text):
    """Shape an article like a registered knowledge source."""
    lines=[line for line in text.splitlines() if line.strip()]
    return dict(id=f"{LIBRARY}:{row['id']}",library_id=LIBRARY,file_id=row['id'],title=row['title']+' '+row['article'],
                sha256=row['sha256'],units=[dict(text=line,loc=f'{i}행') for i,line in enumerate(lines,1)],
                limited=False,kind=row['kind'],institution=row['institution'],effective_date=row['effective_date'],
                enabled=True,current=True,official=row)


def _annual_use(law,query):
    """Each annual-leave use question has its own article; 반일·이월 have none here."""
    q=re.sub(r'\s+','',query)
    for terms,articles in ((('당겨','미리'),{'local':('제7조의3(',)}),(('저축',),{'national':('제16조의3(',),'local':('제7조의10(',)}),
                           (('연속','10일이상'),{'national':('제16조의4(',),'local':('제7조의11(',)}),
                           (('승인','연가계획'),{'national':('제16조(',)})):
        if any(t in q for t in terms):return articles.get(law)
    return None


def expected(topic,query):
    """Return (title, article prefixes) that directly answer a topic for the stated status."""
    from . import knowledge_intent
    found=status(query);place=region(query)
    # Without a status, leave topics keep their existing local-first mapping.
    if not found and not place and topic in knowledge_intent.ARTICLE:return None
    # A fire officer of an unbundled province: the fire decree says the ordinance applies.
    if found=='fire' and not place and topic in FIRE_ORDINANCE:return TITLES['fire'],('제11조(',)
    for law in reads(query):
        prefixes=_annual_use(law,query) if topic=='annual_use' else ARTICLES[law].get(topic)
        if prefixes:return TITLES[law],prefixes
    return None


@lru_cache(maxsize=1)
def summaries():
    try:return tuple(json.loads((BASE/'summaries.json').read_text(encoding='utf-8')))
    except (OSError,ValueError):return ()


def summary(query,reply):
    """Reviewed conclusion-first tree; every sentence must match the cited article."""
    topics=(reply.get('intent') or {}).get('topics',[]);evidence=reply.get('evidence',[])
    if len(topics)!=1:return None
    q=re.sub(r'\s+','',query)
    for card in summaries():
        if topics[0] not in card['topics'] or card.get('when_any') and not any(re.sub(r'\s+','',t) in q for t in card['when_any']):continue
        # A personal case (years served, pay-out, leave of absence) needs the full article, not a table summary.
        if card.get('unless_pattern') and re.search(card['unless_pattern'],q):continue
        # The same article may come from an earlier verified pack with other line breaks;
        # match the verified regulation and article, then require every anchor below.
        from . import official_sources
        ref=next((i for i,h in enumerate(evidence,1) if (h.get('official') or {}).get('title')==TITLES[card['law']] and
                  h['official'].get('article','').startswith(card['article']) and official_sources.metadata(h.get('sha256'))),None)
        if not ref:continue
        items=[]
        for item in card['items']:
            quotes=[re.search(r'\s*'.join(map(re.escape,re.sub(r'\s+','',anchor))),evidence[ref-1]['text']) for anchor in item['anchors']]
            if not all(quotes):break
            items.append(dict(text=item['text'],ref=ref,support_quotes=[m[0] for m in quotes]))
        else:
            return dict(kind='summary',title=card['title'],rule_id='service-rules:'+card['id'],
                        reviewed_source_sha256s=[evidence[ref-1]['sha256']],branches=[dict(label=card['label'],items=items)],
                        note=f"{TITLES[card['law']]}에서 확인한 요약이에요. 소속 기관의 세부 지침·절차는 따로 확인하세요.")
    return None


def special_first(query,hits):
    """Put a close fire/police special rule ahead of the national rule it modifies."""
    found={'fire_national':'fire'}.get(status(query),status(query))
    if found not in {'fire','police'} or not hits:return hits
    top=hits[0]['score'];close=lambda h:(h.get('official') or {}).get('law')==found and h['score']>=top*0.6
    return [h for h in hits if close(h)]+[h for h in hits if not close(h)]


def documents(query,today):
    """Return (docs, notice) for a conduct question, or None for another subject."""
    if not is_subject(query):return None
    found=status(query);place=region(query);q=re.sub(r'\s+','',query)
    docs=[document(row,text) for law in reads(query) for row,text in catalog() if row['law']==law and row['effective_date']<=today.isoformat()]
    notice='' if found or place else '국가·지방·소방·경찰공무원은 적용 조문이 달라요. 신분을 알려주시면 해당 복무규정으로 다시 확인해요.'
    regional=re.search(r'특별휴가|경조사|결혼|사망|출산|장기재직|새내기|생일|육아|돌봄|난임|임신|부모휴가|입영',q)
    if place and found in ('local','fire',None) and regional:
        title=ORDINANCE[place][1]
        notice=(f'시·도 소속 소방공무원의 특별휴가·장기재직휴가는 {title}를 적용해요(소방공무원 복무규정 제11조).' if found=='fire' and regional else
                f'{title}는 도와 도 소속기관 공무원 기준이에요. 시·군 소속이면 해당 시·군 조례를 확인하세요.')
    elif found=='fire' and regional:
        notice='시·도 소속 소방공무원은 국가공무원 복무규정에 없는 특별휴가와 장기재직휴가에 소속 지방자치단체 조례를 적용해요(소방공무원 복무규정 제11조). 공무담에는 현재 경기도 조례만 있어요.'
    elif found=='local' and regional:
        notice='지방공무원의 특별휴가 일부와 장기재직휴가는 소속 지방자치단체 조례로 정해요. 공무담에는 현재 경기도 조례만 있어요. 소속 조례를 확인하세요.'
    return docs,notice
