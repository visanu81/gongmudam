"""Narrow, offline routing for 업무추진비 집행내역 공개 questions.

A local government follows 지방회계관리훈령 제121조 and 별표 2의2 《공개방법》;
a national agency follows the 2026 집행지침 업무추진비 공통지침, which sets no
cycle. 정보공개 청구 questions stay on the 정보공개법 path.
"""
import re


def classify(query):
    q = re.sub(r'\s+', '', query.split('\n업무환경:')[0])
    if '업무추진비' not in q or not any(t in q for t in ('공개', '공표', '홈페이지', '게시')):
        return None
    if any(t in q for t in ('정보공개', '공개청구')):
        return None
    plan = dict(topics=['expense'], rules=[])

    def unavailable(reason):
        return dict(plan, rules=['unsupported'], reason=reason)

    if any(t in q for t in ('공기업', '공단', '공공기관', '교육청', '학교')):
        return unavailable('공기업·공공기관·교육기관은 자체 업무추진비 공개 기준을 따로 확인해야 해요. 해당 기관의 기준을 등록해 주세요.')
    local = any(t in q for t in ('지자체', '지방자치단체', '시청', '군청', '구청', '도청', '지방의회', '시의회', '도의회', '군의회', '구의회'))
    national = any(t in q for t in ('국가기관', '중앙부처', '중앙행정기관', '정부부처'))
    if local == national:
        return unavailable('국가기관인지 지방자치단체(지방의회 포함)인지 알려주세요. 지방은 지방회계관리훈령 제121조와 별표 2의2, '
                           '국가기관은 예산 집행지침의 업무추진비 공통지침으로 공개 기준을 확인해요.')
    plan['rules'] = ['expense-local-disclosure' if local else 'expense-national-disclosure']
    if local and any(t in q for t in ('항목', '단위', '방법', '어떻게', '무엇', '뭘')) and not any(t in q for t in ('주기', '언제', '시기', '기한')):
        plan['lead'] = '공개 단위·항목·방법'
    return plan
