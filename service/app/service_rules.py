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
def _place(*names):
    # A province's own name, not its education office (교육청 has its own ordinance).
    return '(?:'+'|'.join(names)+')(?![가-힣]{0,5}교육)|(?:'+'|'.join(names)+')소방'


ORDINANCE={
 'gyeonggi':(_place('경기도','경기'),'경기도 공무원 복무 조례'),
 'seoul':(_place('서울특별시','서울시'),'서울특별시 공무원 복무 조례'),
 'busan':(_place('부산광역시','부산시'),'부산광역시 공무원 복무 조례'),
 'daegu':(_place('대구광역시','대구시'),'대구광역시 지방공무원 복무 조례'),
 'incheon':(_place('인천광역시','인천시'),'인천광역시 공무원 복무 조례'),
 'daejeon':(_place('대전광역시','대전시'),'대전광역시 지방공무원 복무 조례'),
 'ulsan':(_place('울산광역시','울산시'),'울산광역시 공무원 복무 조례'),
 'sejong':(_place('세종특별자치시','세종시'),'세종특별자치시 지방공무원 복무 조례'),
 'gangwon':(_place('강원특별자치도','강원도'),'강원특별자치도 공무원 복무 조례'),
 'chungbuk':(_place('충청북도','충북'),'충청북도 지방공무원 복무 조례'),
 'chungnam':(_place('충청남도','충남'),'충청남도 공무원 복무 조례'),
 'jeonbuk':(_place('전북특별자치도','전라북도','전북'),'전북특별자치도 지방공무원 복무조례'),
 'gyeongbuk':(_place('경상북도','경북'),'경상북도 공무원 복무 조례'),
 'gyeongnam':(_place('경상남도','경남'),'경상남도 지방공무원 복무 조례'),
 'jeju':(_place('제주특별자치도','제주도'),'제주특별자치도 공무원 복무 조례'),
}
TITLES={'national':'국가공무원 복무규정','local':'지방공무원 복무규정','fire':'소방공무원 복무규정','police':'경찰공무원 복무규정',
        'national_allowance':'공무원수당 등에 관한 규정','local_allowance':'지방공무원 수당 등에 관한 규정',
        'welfare':'공무원 후생복지에 관한 규정','national_rules':'국가공무원 복무규칙',
        'national_pay':'공무원보수규정','local_pay':'지방공무원 보수규정','fire_duty':'소방공무원 당직 및 비상업무 규칙',
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
 # The special-leave article holding each province's long-service (or 자기계발) leave.
 # 서울·충남 ordinances have none in their articles, so the local delegation answers.
 **{key:{'long_service':(article,)} for key,article in (('busan','제15조('),('daegu','제16조('),('incheon','제23조('),('daejeon','제18조('),
    ('ulsan','제13조('),('sejong','제21조('),('gangwon','제14조('),('chungbuk','제14조('),('jeonbuk','제23조('),('gyeongbuk','제17조('),
    ('gyeongnam','제23조('),('jeju','제19조('))},
 'national_rules':{'duty':('제13조(','제15조(','제21조(','제23조(','제37조(','제38조(','제42조(')},
 'welfare':{'welfare_points':tuple(f'제{n}조(' for n in range(5,13)),'welfare_grant':('제10조(','제11조(')},
}
# Allowance articles share numbers in both decrees except those listed separately.
def _label(number):
    main,_,branch=number.partition('의')
    return f'제{main}조'+(f'의{branch}' if branch else '')+'('


_SAME={'allowance_family':'10','allowance_overtime':'15','allowance_holiday':'18의3','allowance_annual':'18의5','allowance_meal':'18',
       'allowance_management':'17의2','allowance_risk':'13','allowance_special':'14','allowance_remote':'12','allowance_position':'18의6',
       'allowance_proxy':'14의2','allowance_night':'16','allowance_holiday_work':'17'}
ARTICLES['national_allowance']={**{t:(_label(n),) for t,n in _SAME.items()},'allowance_diligence':('제7조(',),
    'allowance_childcare':('제11조의3(',),'allowance_senior':('제6조의2(',),'allowance_performance':('제7조의2(',),
    'allowance_housing':('제11조의2(',),'allowance_tuition':('제11조(',)}
ARTICLES['local_allowance']={**{t:(_label(n),) for t,n in _SAME.items()},'allowance_diligence':('제6조(',),
    'allowance_childcare':('제11조의2(',),'allowance_senior':('제5조의2(',),'allowance_performance':('제6조의2(',)}
# Pay articles: (national, local) article numbers for each pay topic.
_PAY={'pay_payday':('20','19'),'pay_initial_step':('8','8'),'pay_promotion_step':('11','10'),'pay_regular_raise':('13','12'),
      'pay_raise_limit':('14','13'),'pay_reassess':('9','9'),'pay_deduct_leave':('28','27'),'pay_deduct_absence':('27','26'),
      'pay_deduct_discipline':('26','25'),'pay_deduct_suspension':('29','28'),'pay_calc':('22','21'),'pay_table':('5','4')}
ARTICLES['national_pay']={t:(_label(n),) for t,(n,_) in _PAY.items()}
ARTICLES['local_pay']={t:(_label(n),) for t,(_,n) in _PAY.items()}
# The fire decree only delegates duty details; the fire agency's rule holds them.
ARTICLES['fire_duty']={'duty':('제3조(','제4조(','제9조(','제9조의2(','제9조의3(','제13조(','제14조(','제20조(','제21조(','제21조의2(')}
# Detail wording -> the fire duty rule's own article for it.
DUTY_DETAIL=(('당직.*면제',('제9조의2(',)),('비상.*면제',('제21조의2(',)),('면제',('제9조의2(','제21조의2(')),('유예',('제9조의3(',)),('편성',('제9조(',)),('교대|휴식',('제4조(',)),
             ('응소',('제21조(',)),('비상근무의?종류|동원',('제13조(',)),('장거리여행',('제24조(',)))
# Allowances and pay follow the pay system, not the conduct decree: fire and police are national.
DOMAINS=(('welfare',r'맞춤형복지|복지점수|복지포인트|후생복지'),('allowance',r'수당|명절휴가비|연가보상|정액급식비|직급보조비|성과상여금|성과급'),
         ('pay',r'호봉|봉급|승급|월급|급여|보수지급|보수계산|보수감액|보수가|보수는|근속가봉'))
# 시·도 소방의 장기재직휴가는 국가 기준이 아니라 조례로 정합니다(소방공무원 복무규정 제11조②).
FIRE_ORDINANCE=('long_service','region_leave')
SUBJECT=re.compile(r'호봉|봉급|승급|월급|급여|보수지급|보수계산|보수감액|보수가|보수는|근속가봉|수당|명절휴가비|연가보상|정액급식비|직급보조비|성과상여금|성과급|맞춤형복지|복지점수|복지포인트|후생복지|장기재직|새내기|생일특별|휴가|연가|병가|공가|특별휴가|경조사|출산|육아시간|모성보호|난임|근무시간|시간외|초과근무|당직|비상근무|비상소집|'
                   r'겸직|영리|정치|복장|복제|지각|조퇴|외출|휴무|포상|국외여행|여행|교대|선서|비밀|친절|복무|토요일|공휴일|근무혁신|유연근무|파견|겸임')


def status(query):
    q=re.sub(r'\s+','',query)
    return next((key for key,pattern in STATUS if re.search(pattern,q)),None)


def region(query):
    q=re.sub(r'\s+','',query)
    return next((key for key,(pattern,_) in ORDINANCE.items() if re.search(pattern,q)),None)


def domain(query):
    q=re.sub(r'\s+','',query)
    # The payable leave days are a conduct-decree rule (연가 일수), not an allowance article.
    if '연가보상' in q and re.search(r'일수|며칠|몇일|\d+일',q):return None
    return next((key for key,pattern in DOMAINS if re.search(pattern,q)),None)


def reads(query):
    """Regulations for the stated status; a known province's ordinance goes first."""
    found=status(query);place=region(query);area=domain(query)
    if area=='welfare':return ('welfare',)
    if area in ('allowance','pay'):
        local,national=('local_allowance','national_allowance') if area=='allowance' else ('local_pay','national_pay')
        if found=='local' or found is None and place:return (local,)
        return (local,national) if found is None else (national,)
    if found=='national':return ('national_rules','national')
    laws=(place,)+READS[found if found else 'local'] if place and found in ('local','fire',None) else READS[found]
    # The fire agency's duty rule is read after the fire decree that delegates to it.
    if found in ('fire','fire_national'):laws=tuple(x for law in laws for x in ((law,'fire_duty') if law=='fire' else (law,)))
    return laws


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
    if topic=='duty' and found in ('fire','fire_national'):
        detail=next((articles for pattern,articles in DUTY_DETAIL if re.search(pattern,re.sub(r'\s+','',query))),None)
        if detail:return TITLES['fire_duty'],detail
    if topic.startswith(('allowance_','welfare_','pay_')):
        law=next((law for law in reads(query) if topic in ARTICLES.get(law,{})),None)
        return (TITLES[law],ARTICLES[law][topic]) if law else None
    # A fire officer of an unbundled province: the fire decree says the ordinance applies.
    if found=='fire' and not place and topic in FIRE_ORDINANCE:return TITLES['fire'],('제11조(',)
    for law in reads(query):
        prefixes=_annual_use(law,query) if topic=='annual_use' else ARTICLES.get(law,{}).get(topic)
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
    from .knowledge_supplement import without_document_numbers
    # An issuance number (예규 제2025-3호) is not a personal case like "3년 재직".
    q=re.sub(r'\s+','',without_document_numbers(query))
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
        # The cited passage can be a slice of a long article; the verified whole article holds the anchors.
        text=next((t for row,t in catalog() if row['sha256']==evidence[ref-1].get('sha256')),evidence[ref-1]['text'])
        items=[]
        for item in card['items']:
            quotes=[re.search(r'\s*'.join(map(re.escape,re.sub(r'\s+','',anchor))),text) for anchor in item['anchors']]
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
    area=domain(query)
    if area=='allowance':
        notice='' if found else '국가공무원(소방·경찰 포함)은 「공무원수당 등에 관한 규정」, 지방공무원은 「지방공무원 수당 등에 관한 규정」을 따라요. 신분을 알려주시면 해당 규정으로 다시 확인해요.'
        if found=='local' or found is None and place:notice='지방공무원 수당 중 일부(특수지근무수당 지역 등)는 자치단체 조례로 달라질 수 있어요.'
        return docs,notice
    if area=='pay':
        notice='' if found else '국가공무원(소방·경찰 포함)은 「공무원보수규정」, 지방공무원은 「지방공무원 보수규정」을 따라요. 신분을 알려주시면 해당 규정으로 다시 확인해요.'
        if re.search(r'봉급표|봉급액|호봉표|\d+급',q):
            table='공무원보수규정 별표 3 등' if found and found!='local' else '지방공무원 보수규정 별표 3 등' if found else '각 보수규정의 봉급표 별표'
            notice=(notice+' ' if notice else '')+f'봉급 금액은 직종별 봉급표({table})에 있어요. 금액표는 공무담에 넣지 않았으니 법제처 원문 별표에서 확인하세요.'
        return docs,notice
    if area=='welfare':
        notice=''
        if found in ('local','fire') or place:
            notice='지방공무원과 지방자치단체에서 근무하는 국가공무원(시·도 소방 포함)은 해당 지방자치단체의 후생복지 조례를 따라요(공무원 후생복지에 관한 규정 제3조). 공무담에는 아직 조례가 없어요.'
        return docs,notice
    regional=re.search(r'특별휴가|경조사|결혼|사망|출산|장기재직|새내기|생일|육아|돌봄|난임|임신|부모휴가|입영',q)
    if place and found in ('local','fire',None) and regional:
        title=ORDINANCE[place][1]
        notice=(f'시·도 소속 소방공무원의 특별휴가·장기재직휴가는 {title}를 적용해요(소방공무원 복무규정 제11조).' if found=='fire' and regional else
                f'{title}는 시·도 본청과 소속기관 공무원 기준이에요. 시·군·구 소속이면 해당 시·군·구 조례를 확인하세요.')
        if '장기재직' in q and 'long_service' not in ARTICLES.get(place,{}):
            notice+=f' {title} 본문에는 장기재직휴가 조항이 없어요. 시행규칙이나 기관 지침을 확인하세요.'
    elif found=='fire' and regional:
        notice='시·도 소속 소방공무원은 국가공무원 복무규정에 없는 특별휴가와 장기재직휴가에 소속 지방자치단체 조례를 적용해요(소방공무원 복무규정 제11조). 소속 시·도를 알려주시면 그 조례로 확인해요(광주·전남 조례는 아직 없어요).'
    elif found=='local' and regional:
        notice='지방공무원의 특별휴가 일부와 장기재직휴가는 소속 지방자치단체 조례로 정해요. 시·도 본청 소속이면 소속 시·도를 알려주세요(광주·전남 조례는 아직 없어요). 시·군·구 소속이면 해당 조례를 확인하세요.'
    return docs,notice


def travel_note(query,topics):
    """(notice, practice) for a Gyeonggi official's travel question: the ordinance applies the
    national travel decree with the exceptions in its 제4조."""
    if not any(t.startswith('travel_') for t in topics) or region(query)!='gyeonggi' or status(query) not in ('local','fire',None):return '',[]
    row,text=next(((r,t) for r,t in catalog() if r['law']=='gyeonggi_travel' and r['article'].startswith('제4조(')),(None,None))
    if not row:return '',[]
    notice='경기도 소속 공무원은 「경기도 공무원 여비 조례」가 공무원 여비 규정을 준용하되 제4조의 예외를 둬요.'
    if {'travel_settlement','travel_card'}&set(topics):
        notice+=' 여비 규정 제8조의2제1항·제4항은 경기도 소속에 준용하지 않아요(조례 제4조제1호). 도의 정산 기준을 확인하세요.'
    if 'travel_local' in topics:
        notice+=' 근무지 내 왕복 2km 이내 근거리 출장은 실비로 지급해요(조례 제4조제4호의2).'
    practice=[dict(id=f"{LIBRARY}:{row['id']}",text=text,quote=text,loc=row['article'],title=row['title']+' '+row['article'],
                   kind=row['kind'],institution=row['institution'],effective_date=row['effective_date'],sha256=row['sha256'],
                   official=row,library_id=LIBRARY,file_id=row['id'],limited=False)]
    return notice,practice
