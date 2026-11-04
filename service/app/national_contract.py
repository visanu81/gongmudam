"""Offline routing for national-agency contract steps: quotes, inspection, payment.

Local governments keep the 지방계약법 path. Only a question that names a
national agency, or a confirmed national affiliation, comes here, so the two
decrees are never mixed.
"""
import re

NATIONAL = ('국가기관', '중앙부처', '중앙행정기관', '국가계약법', '정부부처')
LOCAL = ('지자체', '지방자치단체', '시청', '군청', '구청', '도청', '지방계약법')


def classify(query):
    question, _, context = query.partition('\n업무환경:')
    q = re.sub(r'\s+', '', question); c = re.sub(r'\s+', '', context)
    if any(t in q for t in LOCAL):
        return None
    report = '검사조서' in q and '생략' in q
    if not any(t in q for t in NATIONAL):
        # Only the 검사조서 amount differs between the decrees (국가 이하, 지방 미만);
        # the other steps keep the existing local answer when no body is named.
        amount = any(t in q for t in ('얼마', '금액', '만원', '미만', '이하'))
        if not (report and amount) or '지방공무원' in c:
            return None
        if '국가공무원' not in c:
            return dict(topics=['national_contract'], rules=['unsupported'], ask=True,
                        reason='국가기관인지 지방자치단체인지 알려주세요. 검사조서 작성을 생략할 수 있는 계약금액이 국가기관은 '
                               '3천만원 이하(국가계약법 시행령 제56조), 지방자치단체는 3천만원 미만(지방계약법 제17조·시행령 제65조)으로 달라요.')
    payment = any(t in q for t in ('대금', '대가'))
    if report:
        rule = 'ncontract-inspection-report'
    elif payment and any(t in q for t in ('이자', '지연', '지체', '늦')):
        rule = 'ncontract-interest'
    elif payment and any(t in q for t in ('언제', '기한', '며칠', '까지', '기간')):
        rule = 'ncontract-payment'
    elif any(t in q for t in ('검사', '검수')) and any(t in q for t in ('언제', '기한', '며칠', '까지', '기간')):
        rule = 'ncontract-inspection'
    elif '견적' in q:
        rule = 'ncontract-quote'
    else:
        return None
    return dict(topics=['national_contract'], rules=[rule])
