"""Map stated purposes to leave candidates, never decide an entitlement.

Reviewed scope and distinctions: docs/휴가종류_상황별안내_조사_20261024.md.
Names used for search are separate from the immutable quoted source text.
"""
import re

# "복무 중 어떤 걸 써야 해?" asks which leave to use without saying 휴가.
SERVICE_ASK=re.compile(r'복무(?:중|에서|는|를|로|상)?.{0,6}(?:뭐|뭘|무엇|어떤|어떻게).{0,5}(?:써|쓰|쓸|올|신청|처리|해야|로해|로하|해\?|해$)|근무상황.{0,6}(?:뭐|뭘|무엇|어떤).{0,5}(?:써|쓰|쓸|올|신청)')
WHICH_ASK=re.compile(r'(?<![비값료험])(?:뭐|뭘|무엇|어떤걸|어떤거|어떤것)(?:을|로)?(?:써|쓰|쓸|올려|올리|신청)')


# "건강검진 예산 품의" is office work about a health check, not time off for one.
HEALTH_CHECK=re.compile(r'건강검진|건강진단')
HEALTH_WORK=re.compile(r'예산|품의|지출|집행|계약|업체|대행기관|입찰|구매|결산|비용|검진비|지원|채용|임용|신규|건강진단서|대상자|명단|결과|통보')
HEALTH_TIME_OFF=re.compile(r'공가|휴가|연가|병가|복무|상신|근무일|근무중|출근|결근|다녀|쉬[어고나는려면]|며칠|하루|동행')


def health_work(query):
    q=re.sub(r'\s+','',query.split('\n업무환경:')[0])
    return bool(HEALTH_CHECK.search(q) and HEALTH_WORK.search(q) and not HEALTH_TIME_OFF.search(q))


def asks_which_leave(q):
    return bool(SERVICE_ASK.search(q))


def self_sick(query):
    """Recognize stated own illness preventing work, not a routine visit."""
    q=re.sub(r'\s+', '', query.split('\n업무환경:')[0])
    for clause in re.split(r'[.!?\n;]|하지만|그런데', q):
        if re.search(r'아프지않|아픈(?:건|게)아니|독감이아니', clause):continue
        if re.search(r'(?:제가|내가|저는|본인).{0,15}(?:독감|질병|부상|아파|아프|아픈)', clause) and re.search(r'(?:출근|근무|직무).{0,8}(?:어려|못|불가)', clause):
            return True
        if re.search(r'독감|부상|다쳐|아파|아프|아픈', clause) and asks_which_leave(clause) and not re.search(r'아이|자녀|손자녀|아들|딸|부모|어머니|아버지|배우자|아내|남편|할머니|할아버지|가족', clause):
            return True
    return False


def family_care(query):
    q=re.sub(r'\s+', '', query)
    if any(t in q for t in ('가족돌봄','자녀돌봄휴가','자녀돌봄특별휴가')):
        return True
    # Do not borrow a child's name from a different clause/person's illness.
    clauses=re.split(r'[.!?\n;]|하지만|그런데|내가|제가|본인이|나는|저는', q)
    child=r'(?:손자녀|자녀|아이|아들|딸)'
    illness=r'아프|아파|아픈|아팠|고열|열이|열나|열나요|독감|감기|질병|입원|사고|수술|간병'
    for clause in clauses:
        if re.search(r'건강하|아프지않|아프지는않|아픈(?:건|게|것이|것은)아니',clause):continue
        m=re.search(child+r'.{0,18}?(?:'+illness+r')',clause)
        if m and not re.search(r'교사|선생|의사|친구|본인|배우자|아내|남편',m[0]):
            if re.search(r'휴가|연가|병가|공가|쉬어|쉬고|결근|돌봐|돌보|간호|간병',q) or asks_which_leave(q) or WHICH_ASK.search(q):return True
        # Hospital attendance is distinct from the disease/care clause.
        if re.search(child+r'.{0,15}(?:병원|진료|검진|예방접종)',clause):
            if re.search(r'휴가|동행|데려|같이가|함께가',clause):return True
        if re.search(child+r'.{0,15}(?:휴교|휴원|휴업|담임.*상담|학교.{0,4}상담)',clause) and re.search(r'휴가|쉬어|돌봐|돌보|상담',q):return True
        if re.search(r'(?:부모|어머니|아버지|배우자|조부모|할머니|할아버지).{0,15}(?:'+illness+r')',clause) and (re.search(r'휴가|돌봐|돌보|간호|간병',q) or asks_which_leave(q) or WHICH_ASK.search(q)):return True
    return False


def questions(query):
    """Ask for facts, not for the leave name the user is trying to discover."""
    q=re.sub(r'\s+','',query);items=[]
    if not any(t in q for t in ('국가공무원','국가직','국가기관','중앙부처','소방공무원','지방공무원','지방직')):
        items.append('소속 기관과 국가직·지방직 등 적용 신분을 알려주세요. 기관별 기준을 구분할게요.')
    child=bool(re.search(r'자녀|손자녀|아이|아들|딸',q))
    if child and not re.search(r'\d+세|\d+살|미성년|성인|초등|중학생|고등학생',q):
        items.append('자녀의 나이와 재학 여부를 알려주세요. 성인 자녀라면 적용 조건을 별도로 확인해요.')
    if child and not re.search(r'병원.*(?:동행|같이|데려)|(?:진료|검진|예방접종).*(?:동행|같이)|집에서.*(?:돌봐|돌보)',q):
        items.append('자녀 병원 진료에 동행하는지, 집에서 돌봄이 필요한지 알려주세요.')
    items.append('올해 가족돌봄휴가와 그중 유급으로 사용한 일수, 이번에 필요한 날짜·시간을 확인해 주세요.')
    if child:
        items.append('유급 여부는 자녀 수·나이·재학 여부와 장애 자녀·한부모 조건에 따라 확인해요. 해당하는 조건만 알려주세요.')
    return items


def summary(query,reply):
    """Only reviewed complete legal versions may supply the readable answer."""
    from . import official_sources,knowledge_supplement
    if (reply.get('intent') or {}).get('topics')!=['family_care']:return None
    reviewed={'21d5f034c4c657e13735af53a0f1ce01505505af28be35d7d3b312a66fe0181a',
              '156f83e9646084245c69e35ee1186cdbe52101ebe6489c0f7d134e90acca7f62'}
    expected='국가공무원 복무규정' if knowledge_supplement.national(query) else '지방공무원 복무규정'
    q=re.sub(r'\s+','',query)
    for index,hit in enumerate(reply.get('evidence',[]),1):
        if hit.get('sha256') not in reviewed or not official_sources.metadata(hit['sha256']):continue
        if (hit.get('official') or {}).get('title')!=expected:continue
        def item(text,*anchors):
            quotes=[]
            for anchor in anchors:
                match=re.search(r'\s*'.join(map(re.escape,anchor)),hit['text'])
                if not match:return None
                quotes.append(match[0])
            return dict(text=text,ref=index,support_quotes=quotes)
        reason=item('질병 등으로 규정에서 정한 가족을 돌봐야 한다면, 특별휴가인 가족돌봄휴가부터 확인해요. 적용 여부는 돌봄 사유와 소속 기준을 확인해야 해요.',
                    '가족돌봄휴가','질병, 사고, 노령','자녀 또는 손자녀를 돌봐야')
        if re.search(r'교사|상담|공식행사',q):
            reason=item('자녀·손자녀가 다니는 어린이집·학교의 공식 행사나 교사와의 상담 참여는 가족돌봄휴가 사유인지 확인해요.',
                        '공식 행사','교사와의 상담')
        elif re.search(r'휴업|휴원|휴교',q):
            reason=item('어린이집·학교의 휴업·휴원·휴교 등으로 자녀·손자녀를 돌봐야 한다면 가족돌봄휴가 사유를 확인해요.',
                        '휴업','휴원','휴교','돌봐야 하는 경우')
        hospital=item('병원 진료 동행은 미성년 또는 장애가 있는 자녀·손자녀인지 확인해요. 집에서 아픈 가족을 돌보는 사유와 구분해요.',
                      '미성년자','장애인','병원 진료','동행하는 경우')
        pay=item('가족돌봄휴가는 연간 10일 범위이며 원칙은 무급이에요. 자녀 돌봄의 유급 인정분은 별도 조건이 있어요.',
                 '연간 10일','가족돌봄휴가는 무급으로 하되')
        conditions=item('자녀 돌봄 유급분은 대상 자녀 수·나이·재학 여부, 장애 자녀·한부모 조건과 올해 사용한 일수를 함께 확인해야 해요. 10일 전부를 유급으로 보지 않아요.',
                        '수에 1을 더한 일수','장애인인 자녀','한부모가족지원법')
        nodes=[reason,pay,conditions]
        if re.search(r'병원|진료|검진|예방접종|아프|아파|독감|고열',q) and re.search(r'자녀|아이|아들|딸',q):nodes.insert(1,hospital)
        if not all(nodes):continue
        label='국가공무원 기준' if expected.startswith('국가') else '지방공무원 기준'
        return dict(kind='summary',title='가족돌봄휴가를 신청할 수 있는 상황이에요. 돌봄 대상·사유와 유급 조건을 확인하세요.',rule_id='family-care-situation',
            reviewed_source_sha256=hit['sha256'],branches=[dict(label='상황에 맞는 휴가 후보 · '+label,items=[n for n in (reason,hospital if hospital in nodes else None) if n]),
                dict(label='일수·유급 여부는 별도 확인',items=[pay,conditions])],
            note='소속·신분이 확인되기 전에는 위 기준을 본인에게 적용한다고 확정하지 않아요. 기관 조례·지침과 승인 절차를 함께 확인하세요.')
    return None
