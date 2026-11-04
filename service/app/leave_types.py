"""Offline routing for "which kinds of leave are there": 국가 제14조, 지방 제6조.

Both decrees name the same four kinds, so the answer does not wait for the
body; a named body or a confirmed affiliation gets that decree's overview.
A stated situation keeps the existing leave guidance, which picks a candidate.
"""
import re

ASKS = re.compile(r'휴가.{0,6}(?:종류|뭐가있|뭐있|뭐뭐|무엇이있|뭐가더|어떤게|어떤것|몇가지)|'
                  r'(?:어떤|무슨)(?:특별)?휴가(?:가|는|들)?(?:있|종류)|종류.{0,4}휴가')
SITUATION = ('아프', '아파', '아픈', '다쳐', '결혼', '출산', '사망', '돌봄', '돌봐', '병원', '수술', '입원', '임신',
             '써야', '쓸수', '쓰나', '쓰면', '사용', '제가', '내가', '아이', '자녀', '부모', '배우자', '때', '경우', '인데')
OTHER = ('소방', '경찰', '교원', '교사', '군인', '공무직', '기간제', '회사', '민간')
LOCAL = ('지방공무원', '지방직', '지자체', '지방자치단체', '시청', '군청', '구청', '도청')
NATIONAL = ('국가공무원', '국가직', '국가기관', '중앙부처', '중앙행정기관', '정부부처')


def classify(query):
    question, _, context = query.partition('\n업무환경:')
    q = re.sub(r'\s+', '', question); c = re.sub(r'\s+', '', context)
    if not ASKS.search(q) or '휴가비' in q or any(t in q for t in OTHER + SITUATION):
        return None
    local = any(t in q for t in LOCAL)
    national = any(t in q for t in NATIONAL)
    if local == national:
        local, national = '지방공무원' in c, '국가공무원' in c
    side = 'both' if local == national else 'local' if local else 'national'
    plan = dict(topics=['leave_types'], rules=[f'leave-types-{side}'])
    if '특별휴가' in q:
        plan['lead'] = '특별휴가 세부 종류'
    return plan
