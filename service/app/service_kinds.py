"""Offline routing for "which kinds are there": 공가 사유, 징계 종류·효력, 유연근무 유형,
공무원의 의무, 복무 위반, 승진소요최저연수, 성과상여금 지급 시기.

공가 and 징계 are the same in the national and local rules, so they do not wait
for the body. 유연근무 types come from the 인사혁신처 예규, which binds national
officers only, and a local answer says so instead of borrowing them.
A specific case (헌혈, 징계 시효) keeps its existing route.
"""
import re

from . import leave_situations

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


DUTY_ASK = re.compile(r'(?:공무원|복무).{0,4}의무.{0,6}(?:뭐|무엇|알려|종류|있|어떤)|(?:공무원|복무).{0,4}의무$')
VIOLATION_ASK = re.compile(r'(?:복무|의무).{0,6}(?:위반|어기|어겼).{0,10}(?:어떻게|뭐|처벌|징계|불이익|되)')
VIOLATION_CASE = ('음주', '성비위', '금품', '겸직', '시효', '감경', '기준')
PROMOTION_ASK = re.compile(r'승진.{0,10}(?:최저연수|소요|몇년|얼마나|기간|연수|걸려|걸리)')
PROMOTION_CASE = ('시험', '가산', '심사', '명부', '후보', '점수', '호봉', '수당', '교육')
PROMOTION_YEARS = {4: '3년', 5: '3년', 6: '2년', 7: '1년', 8: '1년', 9: '1년'}
POSTAL_YEARS = {2: '3년', 3: '1년 6개월', 4: '1년 6개월', 5: '1년 6개월', 6: '1년 6개월', 7: '1년', 8: '1년', 9: '1년'}
BONUS_ASK = re.compile(r'(?:성과상여금|성과급).{0,8}(?:언제|시기|지급일|지급날|몇월)|언제.{0,6}(?:성과상여금|성과급)')
BONUS_CASE = ('퇴직', '휴직', '복직', '파견', '전입', '징계', '신규', '입대', '연봉', '이의', '평가', '등급', '얼마', '재배분')
BONUS_TITLE = '지침에 정해진 지급 달은 없고, 기관이 2월 말까지 세우는 지급계획에서 지급시기를 정해요. 소속 기관의 계획을 확인하세요.'
# Named in 복무규정 제19조 제1호~제4호 and read there, not guessed from the word alone.
PUBLIC_LEAVE_CASES = (('예비군', '예비군 훈련은 법령에 따른 소집·훈련 참가로 공가 사유예요.'),
                      ('민방위', '민방위 훈련도 법령에 따른 훈련 참가이면 공가 사유예요.'),
                      ('병역판정', '병역판정검사는 공가 사유예요.'),
                      ('투표', '법률에 따른 투표 참가는 공가 사유예요.'),
                      ('승진시험', '승진시험 응시는 공가 사유예요.'),
                      ('전직시험', '전직시험 응시는 공가 사유예요.'))


def side_of(q, c):
    local = any(t in q for t in LOCAL)
    national = any(t in q for t in NATIONAL)
    if local == national:
        local, national = '지방공무원' in c, '국가공무원' in c
    return 'both' if local == national else 'local' if local else 'national'


def promotion_title(q, side):
    """The named rank as the conclusion. 3급 and above are in 지방공무원 임용령 제33조 only."""
    if '우정' in q:  # 우정직 has its own periods in 공무원임용령 제31조 제1항 제2호.
        postal = re.search(r'우정([2-9])급', q)
        return f'우정{postal[1]}급에서 승진하려면 {POSTAL_YEARS[int(postal[1])]} 이상 해당 계급에 재직해야 해요.' if postal else None
    target = re.search(r'([1-8])급으로', q)
    named = re.search(r'([2-9])급', q)
    rank = int(target[1]) + 1 if target else int(named[1]) if named else None
    if rank is None:
        return None
    start = f'{target[1]}급으로 승진하려면 {rank}급에서' if target else f'{rank}급에서 승진하려면'
    if rank >= 4:
        return f'{start} {PROMOTION_YEARS[rank]} 이상 해당 계급에 재직해야 해요.'
    if side == 'local':
        return f'{start} 2년 이상 해당 계급에 재직해야 해요.'
    if side == 'national':
        return f'공무원임용령 제31조 일반직 기간에는 {rank}급이 없어요. 4·5급 3년, 6급 2년, 7·8·9급 1년 이상이 정해져 있어요.'
    return f'지방공무원은 {rank}급에서 2년 이상 재직해야 해요. 국가공무원 {rank}급은 공무원임용령 제31조 일반직 기간에 없어요.'


def classify(query):
    question, _, context = query.partition('\n업무환경:')
    q = re.sub(r'\s+', '', question); c = re.sub(r'\s+', '', context)
    # A confirmed affiliation counts too: 소방·경찰 follow their own decrees.
    if any(t in q + c for t in OTHER):
        return None
    side = side_of(q, c)
    if leave_situations.asks_which_leave(q):
        named = next((t for name, t in PUBLIC_LEAVE_CASES if name in q), None)
        if named:
            return dict(topics=['leave_types'], rules=[f'official-leave-{side}'], title=named)
    if DUTY_ASK.search(q):
        return dict(topics=['duties'], rules=[f'duties-{side}'])
    if VIOLATION_ASK.search(q) and not any(t in q for t in VIOLATION_CASE):
        return dict(topics=['duties'], rules=[f'violation-{side}'])
    if PROMOTION_ASK.search(q) and not any(t in q for t in PROMOTION_CASE):
        return dict(topics=['promotion'], rules=['promotion-national' if '우정' in q else f'promotion-{side}'], title=promotion_title(q, side))
    if BONUS_ASK.search(q) and not any(t in q for t in BONUS_CASE):
        return dict(topics=['bonus'], rules=[f'bonus-timing-{side}'], title=BONUS_TITLE)
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
