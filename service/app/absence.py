"""Offline routing for 휴직 questions: 국가공무원법 제71~73조, 지방공무원법 제63~65조.

Both laws give the same grounds and periods, so the answer does not wait for
the body. A question about one kind shows that kind first and leaves the
others out. Pay during absence keeps the 보수규정 route.
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
NATIONAL = ('국가공무원', '국가직', '국가기관', '중앙부처', '중앙행정기관', '정부부처')


def classify(query):
    question, _, context = query.partition('\n업무환경:')
    q = re.sub(r'\s+', '', question); c = re.sub(r'\s+', '', context)
    returning = any(t in q for t in RETURN) and ('휴직' in q or '복직' in q)
    if not ('휴직' in q or returning) or any(t in q for t in ELSEWHERE + OTHER) or any(t in c for t in OTHER):
        return None
    kinds = [label for label, words in KINDS if any(t in q for t in words)]
    if not (returning or any(t in q for t in ASKS) or (kinds and q.endswith(('휴직', '휴직?')))):
        return None
    local = any(t in q for t in LOCAL)
    national = any(t in q for t in NATIONAL)
    if local == national:
        local, national = '지방공무원' in c, '국가공무원' in c
    side = 'both' if local == national else 'local' if local else 'national'
    plan = dict(topics=['absence'], rules=[f'absence-{side}'])
    if returning and not kinds:
        plan['only'] = ['신분과 복직']
    elif kinds:
        plan['only'] = kinds + ['신분과 복직']
    elif any(t in q for t in ('종류', '뭐가있', '뭐있', '무슨', '어떤', '사유')):
        plan['only'] = ['휴직 종류', '신분과 복직']
    else:
        plan['title'] = '휴직 기간은 종류마다 달라요. 육아 3년 이내, 질병 1년 이내(연장 가능), 가족돌봄 1년 이내(재직 중 총 3년), 유학 3년 이내(연장 가능)예요.'
    return plan
