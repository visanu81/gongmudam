"""Offline routing for "which kinds are there": 공가 사유, 징계 종류·효력, 유연근무 유형.

공가 and 징계 are the same in the national and local rules, so they do not wait
for the body. 유연근무 types come from the 인사혁신처 예규, which binds national
officers only, and a local answer says so instead of borrowing them.
A specific case (헌혈, 징계 시효) keeps its existing route.
"""
import re

OTHER = ('교원', '교사', '교육공무원', '경찰', '소방', '군인', '공무직', '기간제', '회사', '민간')
LOCAL = ('지방공무원', '지방직', '지자체', '지방자치단체', '시청', '군청', '구청', '도청')
NATIONAL = ('국가공무원', '국가직', '국가기관', '중앙부처', '중앙행정기관', '정부부처')
OFFICIAL_ASK = re.compile(r'공가.{0,6}(?:종류|언제|사유|뭐가|뭐있|뭐뭐|어떤|무슨|경우)|(?:어떤|무슨).{0,6}공가')
OFFICIAL_CASE = ('헌혈', '검진', '건강진단', '예비군', '민방위', '투표', '시험', '병역', '소집', '소환', '면접', '훈련', '행사', '접종', '전보', '이사', '며칠', '일수', '신청', '증빙')
DISCIPLINE_ASK = re.compile(r'징계.{0,4}(?:종류|뭐가|뭐있|뭐뭐|몇가지|어떤|구분)')
DISCIPLINE_EFFECT = re.compile(r'(?:강등|정직|감봉|견책).{0,10}(?:뭐|뜻|얼마|기간|몇|효력|어떻게되|불이익)')
DISCIPLINE_CASE = ('시효', '위원회', '부가금', '절차', '감경', '양정', '기준', '사유', '음주', '성비위', '금품', '말소', '재심')
EFFECT_TITLES = (('강등', '강등은 1계급 아래로 내리고 3개월간 직무에 종사하지 못하며 그동안 보수를 전액 감해요.'),
                 ('정직', '정직은 1개월 이상 3개월 이하 기간 동안 직무에 종사하지 못하고 보수를 전액 감해요.'),
                 ('감봉', '감봉은 1개월 이상 3개월 이하 기간 동안 보수의 3분의 1을 감해요.'),
                 ('견책', '견책은 지난 잘못을 훈계하고 뉘우치게 하는 징계예요.'))
FLEX_ASK = re.compile(r'유연근무.{0,6}(?:종류|유형|뭐가|뭐있|뭐뭐|어떤|무슨|형태)|(?:어떤|무슨).{0,6}유연근무')


def side_of(q, c):
    local = any(t in q for t in LOCAL)
    national = any(t in q for t in NATIONAL)
    if local == national:
        local, national = '지방공무원' in c, '국가공무원' in c
    return 'both' if local == national else 'local' if local else 'national'


def classify(query):
    question, _, context = query.partition('\n업무환경:')
    q = re.sub(r'\s+', '', question); c = re.sub(r'\s+', '', context)
    # A confirmed affiliation counts too: 소방·경찰 follow their own decrees.
    if any(t in q + c for t in OTHER):
        return None
    side = side_of(q, c)
    if OFFICIAL_ASK.search(q) and not any(t in q for t in OFFICIAL_CASE):
        return dict(topics=['leave_types'], rules=[f'official-leave-{side}'])
    if not any(t in q for t in DISCIPLINE_CASE):
        if DISCIPLINE_ASK.search(q):
            return dict(topics=['discipline'], rules=[f'discipline-{side}'])
        if DISCIPLINE_EFFECT.search(q):
            named = next((t for name, t in EFFECT_TITLES if name in q), None)
            return dict(topics=['discipline'], rules=[f'discipline-{side}'], lead='종류별 효력', title=named)
    if FLEX_ASK.search(q):
        return dict(topics=['flex'], rules=[f'flex-{side}'])
    return None
