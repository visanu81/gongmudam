"""Conservative, model-free wording and affiliation matching for owned sources.

Aliases expand search words only. They never create rule text or infer that a
parent institution, another department, or a similarly named agency applies.
"""
import re

CATEGORIES=('미분류','예산·회계','복무·휴가','출장·여비','물품·계약','교육·행사','문서·기록','보안·개인정보','기타')
SUBJECTS={
    'education':('교육','연수','수강'),
    'attendance':('희망자','참석자','참가자','참여자','참석','참가','참여'),
    'travel':('출장','여비'),
    'leave':('휴가','복무','연가'),
    'family':('자녀','아이','가족돌봄','자녀돌봄'),
    'sick':('병가','질병','아파','아픈'),
    'purchase':('물품','사무용품','비품','구매','구입'),
    'budget':('예산','지출과목','통계목','세목','예산목','예산과목'),
    'inspection':('검수','검사','납품'),
    'overtime':('초과근무','시간외근무','야근'),
    'security':('보안점검','보안검사'),
    'privacy':('개인정보','주민등록번호'),
    'record':('기록물','문서접수','문서등록'),
    'sidejob':('겸직','부업','영리업무'),
}
FACETS={
    'deadline':('기한','마감','언제까지','언제내','언제제출','며칠전','몇일전','언제'),
    'form':('서식','양식','신청서','확인서','제출서'),
    'fields':('필수항목','기재항목','무엇을적','뭘적','어떤항목','어떤내용','적어야','써야'),
    'materials':('증빙','준비물','구비서류','준비서류','필요서류','제출서류','뭘준비','무엇을준비','준비해야'),
    'budget':SUBJECTS['budget']+('무슨목','어느목','어떤목'),
    'amount':('얼마','금액','지급액','단가'),
}
STOP={'어떻게','알려','알려줘','알려주세요','해주세요','하는','하려','하려고','하는데','하려는데','우리','기관','소속','업무','처리','자료','관련','확인','신청','제출','필요','대해','대한','무엇','어떤','것은','입니다','해요','돼요','되나요','있나요','있어','언제','서식','양식','기한','마감','필수','항목','국가공무원','지방공무원','업무환경','필요한','서류','사용','지급','방법','가능','종류','기준','확인할','언제야','어디서','적으면','쓰면','하면','하는지','되는지','내면','준비','하려는','좋을지','있어요','있을까','궁금해요','문의','문의해요','알고','싶어요'}

def flat(value):return ''.join(str(value).split()).casefold()

def concepts(text,groups):
    text=flat(text)
    return {key for key,words in groups.items() if any(w in text for w in words)}

def expand(query):
    keys=concepts(query,SUBJECTS)
    facets=concepts(query,FACETS)
    return query+' '+' '.join(w for k in sorted(keys) for w in SUBJECTS[k])+' '+' '.join(w for k in sorted(facets) for w in FACETS[k][:3])

def terms(text):
    result=set()
    for word in re.findall(r'[가-힣A-Za-z]{2,}',text):
        word=re.sub(r'(?:으로|에서|에게|까지|부터|하려고|하려는데|하려면|해야|하고|하는|에는|은|는|이|가|을|를|의|에|도|와|과)$','',word)
        if len(word)>=2 and word not in STOP:result.add(word.casefold())
    return result

def agency_pattern(name):
    # Keep word boundaries: 부산광역시 is not an explicit mention of that
    # institution inside 부산광역시교육청. Whitespace variation is harmless.
    letters=[re.escape(c) for c in flat(name)]
    boundary=r'(?=$|[^가-힣A-Za-z0-9])'
    return r'(?<![가-힣A-Za-z0-9])'+r'\s*'.join(letters)+r'(?=$|[^가-힣A-Za-z0-9]|(?:에서|에는|으로|은|는|의|에|와|과|도|이|가|을|를)'+boundary+r')'

def without_agency(query,name):return re.sub(agency_pattern(name),' ',query,flags=re.IGNORECASE)

def named_agencies(query):
    names=re.findall(r'[가-힣A-Za-z0-9]+(?:시청|군청|구청|교육청|소방서|경찰서|공단|공사|대학교|기관|의회|사무처)',query)
    return [n for n in names if n not in {'우리기관','소속기관','본기관','국가기관','지방기관','교육기관'}]

def relevant(query,source):
    """Require a specific subject, plus any requested discriminating facet."""
    query=without_agency(query,source.get('institution','')) if source.get('institution') else query
    text='\n'.join([source.get('title',''),*source.get('keywords',[]),*(u['text'] for u in source.get('units',[]))])
    asked=concepts(query,FACETS);available=concepts(text,FACETS)
    # Budget/amount questions must never fall back to a nearby inspection rule.
    if asked-available:return False
    residual=query
    for word in sorted({w for group in (*SUBJECTS.values(),*FACETS.values()) for w in group},key=len,reverse=True):
        residual=residual.replace(word,' ')
    # A familiar topic word alone cannot answer a new specific subject such as
    # '교육 홍보물 저작권'. Keep distinctive unmatched nouns as a relevance gate.
    unknown={w for w in terms(residual) if len(w)>=3 and not re.search(r'(?:려고|려는데|려면|나요|가요|까요|세요|해줘|인가|인지|해도|알려|까지)$',w)}
    if unknown and not unknown&terms(text):return False
    if any(flat(k) in flat(query) for k in source.get('keywords',[])):return True
    shared=concepts(query,SUBJECTS)&concepts(text,SUBJECTS)
    if shared-{'sick','attendance'}:return True
    overlap=terms(query)&terms(text)
    return bool(shared and overlap) or len(overlap)>=2

FRAMEWORKS={'national_public_official':'국가공무원','local_public_official':'지방공무원',
            'fire_public_official':'소방공무원','police_public_official':'경찰공무원','other':''}
# Fire and police officers are national public officials under their own decrees.
NATIONAL_FRAMEWORKS={'national_public_official','fire_public_official','police_public_official'}
NATIONAL_FIRE=r'소방청|중앙소방학교|국립소방연구원|중앙119구조본부'


def provincial(profile):
    """A province's own agency, not one of its cities, counties or education office."""
    region=flat(profile.get('region',''));organization=profile.get('organization','').split()
    if not region or not organization or not flat(organization[0]).startswith(region):return False
    if '교육' in flat(profile['organization']):return False
    return not (len(organization)>1 and re.search(r'[시군구]$',organization[1]))


def personnel_label(profile):
    """Status wording for common-law search; the region only where its ordinance applies."""
    framework=profile['personnel_framework'];label=FRAMEWORKS.get(framework,'')
    if framework=='fire_public_official':
        return '소방청 소속 '+label if re.search(NATIONAL_FIRE,flat(profile['organization'])) else f"{profile['region']} 소속 {label}".strip()
    if framework=='local_public_official' and provincial(profile):return f"{profile['region']} 소속 {label}"
    return label


def clean_profile(value):
    if not isinstance(value,dict) or value.get('confirmed') is not True:return None
    framework=value.get('personnel_framework')
    if framework not in FRAMEWORKS:return None
    fields={k:value.get(k,'') for k in ('organization','department','region')}
    if any(not isinstance(v,str) or len(v)>300 or '\n' in v or '\r' in v for v in fields.values()):return None
    if len(flat(fields['organization']))<2:return None
    return dict(confirmed=True,personnel_framework=framework,**fields)

def scoped_sources(query,sources,profile=None):
    """Explicit question scope wins. Affiliation matches a whole agency name."""
    mentions=[(m.start(),m.end(),name) for name in {s['institution'] for s in sources}
              for m in re.finditer(agency_pattern(name),query,re.IGNORECASE)]
    explicit={name for start,end,name in mentions if not any(a<=start and end<=b and b-a>end-start for a,b,_ in mentions)}
    named=named_agencies(query)
    if explicit and any(not any(flat(n) in flat(name) for name in explicit) for n in named):return [],'explicit_other'
    if explicit:return [s for s in sources if s['institution'] in explicit],'question'
    profile=clean_profile(profile)
    if not profile:return [],'missing'
    own=flat(profile['organization'])
    # An unknown named agency or an explicit request for another institution is
    # not permission to answer with the user's own institution's rules.
    if own in flat(query) and not re.search(agency_pattern(profile['organization']),query,re.IGNORECASE):return [],'explicit_other'
    if re.search(r'다른\s*기관|타\s*기관|타기관|다른\s*소속',query) or any(flat(n) not in own for n in named):return [],'explicit_other'
    national=bool(re.search(r'국가공무원|국가직|중앙부처|국가기관',query))
    local=bool(re.search(r'지방공무원|지방직|지방자치단체',query))
    if national and profile['personnel_framework']=='local_public_official' or local and profile['personnel_framework'] in NATIONAL_FRAMEWORKS:return [],'explicit_other'
    return [s for s in sources if flat(s['institution'])==own],'affiliation'

def scope_query(query,profile,organizations=()):
    """Supply only confirmed personnel scope to common-law search."""
    profile=clean_profile(profile)
    if not profile or re.search(r'국가공무원|국가직|지방공무원|지방직|중앙부처|국가기관|지방자치단체|다른\s*기관|타기관',query):return query
    # Asking about another status (a local official asking about fire officers) drops the own scope.
    own={'fire_public_official':'소방','police_public_official':'경찰'}.get(profile['personnel_framework'])
    if any(word in flat(query) and word!=own for word in ('소방','경찰')):return query
    if any(flat(n) not in flat(profile['organization']) for n in named_agencies(query)):return query
    mentioned=[name for name in organizations if re.search(agency_pattern(name),query,re.IGNORECASE)]
    if any(flat(name)!=flat(profile['organization']) for name in mentioned):return query
    label=personnel_label(profile)
    return query+'\n업무환경: '+label if label and len(query)<2950 else query
