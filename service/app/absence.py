"""Offline routing for 휴직 questions: 국가공무원법 제71~73조, 지방공무원법 제63~65조.

Both laws give the same grounds and periods, so the answer does not wait for
the body. A question about one kind shows that kind first and leaves the
others out. Pay during absence keeps the 보수규정 route.

How to apply and return comes from 공무원 임용규칙 (national) and 지방공무원 인사제도
운영지침 (local). Only the national rule has a form for every kind; the local one
has only 자기개발휴직's, and the answer says so instead of borrowing national forms.
"""
import re

KINDS = (('육아 휴직', ('육아', '양육', '임신', '출산')),
         ('질병 휴직', ('질병', '공무상', '요양')),
         ('가족돌봄 휴직', ('가족돌봄', '돌봄', '간병', '부양', '돌보')),
         ('배우자 동반 휴직', ('동반',)),
         ('유학 휴직', ('유학',)),
         ('연수 휴직', ('연수',)),
         ('고용 휴직', ('고용', '채용', '민간기업', '국제기구')),
         ('자기개발 휴직', ('자기개발', '학습', '연구과제')),
         ('병역 휴직', ('병역', '군입대', '입대', '군복무')),
         ('생사불명 휴직', ('생사', '소재불명', '실종')),
         ('노조 전임 휴직', ('노조', '노동조합', '전임자')))
ASKS = ('기간', '몇년', '몇개월', '얼마나', '언제까지', '종류', '뭐가있', '뭐있', '무슨', '어떤', '사유', '연장', '총', '최대')
RETURN = ('복직', '복귀')
# Pay, service-period and other subjects have their own rules; procedure and forms are not in these articles.
ELSEWHERE = ('봉급', '월급', '수당', '보수', '급여', '상여', '연봉', '연가', '승진', '경력', '호봉', '연금', '재직기간에', '신청', '서류', '서식', '결재', '시스템')
OTHER = ('교원', '교사', '교육공무원', '경찰', '소방', '군인', '공무직', '기간제', '회사', '민간인', '근로자', '고용보험')
LOCAL = ('지방공무원', '지방직', '지자체', '지방자치단체', '시청', '군청', '구청', '도청')
PROCEDURE_ASK = re.compile(r'신청|절차|서류|서식|제출|증빙|진단서|복직원|복무상황|방법|(?:휴직|복직)(?:은|는|을|를)?어떻게(?:해|하|신청|받)|어떻게(?:신청|복직|휴직)')
# Pay and service-period subjects, changes to a leave already given, and 고용·민간근무휴직's own procedures.
PROCEDURE_ELSE = ('봉급', '월급', '수당', '보수', '급여', '상여', '연봉', '연가', '승진', '경력', '호봉', '연금', '재직기간에', '결재', '시스템',
                  '연장', '취소', '변경', '철회', '거부', '반려', '며칠', '언제까지', '고용', '채용', '민간', '국제기구')
FORMS = {'육아 휴직': ('육아휴직 신청서', 41), '가족돌봄 휴직': ('가족돌봄휴직 신청서', 42), '유학 휴직': ('국외유학휴직 신청서', 38),
         '연수 휴직': ('연수휴직 신청서', 39), '배우자 동반 휴직': ('해외동반휴직 신청서', 40), '자기개발 휴직': ('자기개발휴직 신청서', 32)}
BY_APPOINTMENT = ('병역 휴직', '생사불명 휴직', '노조 전임 휴직')
TO_NATIONAL = '사유 증빙자료를 임용권자 또는 임용제청권자에게 내요.'
CHECK_LOCAL = '소속 기관 인사부서에 서식을 확인하세요.'
NATIONAL = ('국가공무원', '국가직', '국가기관', '중앙부처', '중앙행정기관', '정부부처')


def side_of(q, c):
    local = any(t in q for t in LOCAL)
    national = any(t in q for t in NATIONAL)
    if local == national:
        local, national = '지방공무원' in c, '국가공무원' in c
    return 'both' if local == national else 'local' if local else 'national'


def procedure_title(kind, side):
    if kind == '질병 휴직':
        return '질병휴직은 요양기관 진단서나 사유 증빙자료를 바탕으로 휴직 여부를 결정해요.'
    if kind in BY_APPOINTMENT:
        return f'{kind.replace(" ", "")}은 신청과 관계없이 임용권자가 명해요.'
    if kind == '자기개발 휴직':
        national = f'국가공무원은 별지 제32호 신청서와 {TO_NATIONAL}'
        local = '지방공무원은 별지 제6호 신청서에 자기개발계획을 적어 임용권자에게 내요.'
        return {'national': national, 'local': local}.get(side, f'{national} {local}')
    if kind:
        form, number = FORMS[kind]
        national = f'{form}(공무원 임용규칙 별지 제{number}호)와 {TO_NATIONAL}'
        local = f'지방공무원 {kind.replace(" ", "")}은 임용권자가 명해요. {CHECK_LOCAL}'
        return {'national': national, 'local': local}.get(side, f'국가공무원은 {national} 지방공무원은 {CHECK_LOCAL}')
    national = f'휴직 종류별 신청서와 {TO_NATIONAL}'
    if side == 'national':
        return national
    if side == 'local':
        return f'지방공무원 휴직은 임용권자가 명해요. 운영지침에 서식이 있는 것은 자기개발휴직뿐이니 다른 휴직은 {CHECK_LOCAL}'
    return f'국가공무원은 {national} 지방공무원은 {CHECK_LOCAL}'


def procedure(q, c):
    """How to apply for, report during and return from a 휴직."""
    if not ('휴직' in q or '복직' in q) or not PROCEDURE_ASK.search(q) or any(t in q for t in PROCEDURE_ELSE):
        return None
    side = side_of(q, c)
    plan = dict(topics=['absence_procedure'], rules=[f'absence-procedure-{side}'])
    kind = next((label for label, words in KINDS if any(t in q for t in words)), None)
    if '복무상황' in q:
        national = '국가공무원은 매 반기 복무상황을 보고해요.'
        local = '지방공무원은 매 반기, 질병·유학·육아·자기개발 휴직은 매 분기 복무상황을 보고해요.'
        return dict(plan, only=['휴직 중 보고'], title={'national': national, 'local': local}.get(side, f'{national} {local}'))
    # "휴직 복직 절차" asks about both; "육아휴직 복직 절차" and "복직 서류" ask about returning.
    if '복직' in q and (kind or not re.search(r'휴직(?:및|과|,|·|ㆍ)?복직|휴직신청', q)):
        if kind == '질병 휴직':
            return dict(plan, only=['질병 휴직', '복직'], title='질병휴직 복직은 진단서나 복직 사유 증빙자료로 정상 근무 가능 여부를 판단한 뒤 명해요.')
        return dict(plan, only=['복직'], title='휴직 사유가 없어지면 30일 이내에 신고하고, 기간이 끝났으면 30일 이내에 복귀 신고를 하면 당연히 복직돼요.')
    if kind in BY_APPOINTMENT:
        return dict(plan, only=['누가 명하나', '복직'], title=procedure_title(kind, side))
    if kind:
        return dict(plan, only=[kind, '복직', '휴직 중 보고'], title=procedure_title(kind, side))
    return dict(plan, only=['종류별 신청 방법', '누가 명하나', '복직', '휴직 중 보고'], title=procedure_title(None, side))


def classify(query):
    question, _, context = query.partition('\n업무환경:')
    q = re.sub(r'\s+', '', question); c = re.sub(r'\s+', '', context)
    if not any(t in q + c for t in OTHER):
        plan = procedure(q, c)
        if plan:
            return plan
    returning = any(t in q for t in RETURN) and ('휴직' in q or '복직' in q)
    if not ('휴직' in q or returning) or any(t in q for t in ELSEWHERE + OTHER) or any(t in c for t in OTHER):
        return None
    kinds = [label for label, words in KINDS if any(t in q for t in words)]
    if not (returning or any(t in q for t in ASKS) or (kinds and q.endswith(('휴직', '휴직?')))):
        return None
    plan = dict(topics=['absence'], rules=[f'absence-{side_of(q, c)}'])
    if returning and not kinds:
        plan['only'] = ['신분과 복직']
    elif kinds:
        plan['only'] = kinds + ['신분과 복직']
    elif any(t in q for t in ('종류', '뭐가있', '뭐있', '무슨', '어떤', '사유')):
        plan['only'] = ['휴직 종류', '신분과 복직']
    else:
        plan['title'] = '휴직 기간은 종류마다 달라요. 육아 3년 이내, 질병 1년 이내(연장 가능), 가족돌봄 1년 이내(재직 중 총 3년), 유학 3년 이내(연장 가능)예요.'
    return plan
