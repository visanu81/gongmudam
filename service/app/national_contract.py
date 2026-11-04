"""Offline routing for national-agency contract steps: quotes, inspection, payment.

Local governments keep the 지방계약법 path. Only a question that names a
national agency comes here, so the two decrees are never mixed.
"""
import re


def classify(query):
    q = re.sub(r'\s+', '', query.split('\n업무환경:')[0])
    if not any(t in q for t in ('국가기관', '중앙부처', '중앙행정기관', '국가계약법', '정부부처')):
        return None
    if any(t in q for t in ('지자체', '지방자치단체', '시청', '군청', '구청', '도청', '지방계약법')):
        return None
    payment = any(t in q for t in ('대금', '대가'))
    if '검사조서' in q and '생략' in q:
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
