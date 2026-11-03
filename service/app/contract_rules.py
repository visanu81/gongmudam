"""Narrow, offline routing for 수의계약 amount limits and grounds.

The contracting body decides the decree: a national agency follows 국가계약법
시행령 제26조, a local government 지방계약법 시행령 제25조. The selection
procedure and quotes (제30조) stay on the existing goods-quote path.
"""
import re


def classify(query):
    q = re.sub(r'\s+', '', query.split('\n업무환경:')[0])
    if '수의계약' not in q:
        return None
    if any(t in q for t in ('선정', '절차', '견적')) and not any(t in q for t in ('한도', '금액', '얼마', '이하', '요건')):
        return None
    if not any(t in q for t in ('한도', '금액', '얼마', '이하', '요건', '기준', '가능', '할수있', '되나', '돼', '되요', '되나요', '경우', '사유')):
        return None
    plan = dict(topics=['contract'], rules=[])

    def unavailable(reason):
        return dict(plan, rules=['unsupported'], reason=reason)

    if any(t in q for t in ('공기업', '공단', '공공기관', '민간기업', '사기업', '교육청', '학교')):
        return unavailable('공기업·공공기관·교육기관은 자체 계약 규정이나 별도 기준을 먼저 확인해야 해요. 해당 기관의 계약 규정을 등록해 주세요.')
    local = any(t in q for t in ('지자체', '지방자치단체', '시청', '군청', '구청', '도청', '지방계약법', '지방의회'))
    national = any(t in q for t in ('국가기관', '중앙부처', '중앙행정기관', '국가계약법', '정부부처'))
    if local == national:
        return unavailable('계약하는 곳이 국가기관인지 지방자치단체인지 알려주세요. 국가기관은 국가계약법 시행령 제26조, '
                           '지방자치단체는 지방계약법 시행령 제25조로 수의계약 금액과 사유를 확인해요.')
    if any(t in q for t in ('조달청', '나라장터', '긴급입찰', '예정가격', '분할계약', '쪼개')):
        return unavailable('질문한 조달·예정가격·분할 계약 판단은 수의계약 사유 조문만으로 답할 수 없어요. 해당 계약 예규나 기관 기준이 필요해요.')
    plan['rules'] = ['contract-local-private' if local else 'contract-national-private']
    return plan
