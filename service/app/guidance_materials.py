"""Describe missing operational data without inventing institutional facts.

Only used after retrieval found no direct evidence. These are requests for
materials, not legal rules or automatic connections to business databases.
"""
import re
from . import leave_situations, personnel_scope

CARD_USE=('카드 사용 기준 자료', '카드 사용과 정산에 직접 적용되는 기관·회계 기준을 확인해 주세요. 출장 여비 기준을 대신 적용하지 않아요.')


def scope_hold(reasons):
    """Say why the registered text was held back, instead of reporting it as missing."""
    if '사건일' in reasons or '과거 시점' in reasons:
        return ('질문한 시점의 원문 자료', '질문한 시점에 시행된 원문이 등록되어 있지 않아요. 등록된 판본은 그 뒤에 시행된 것이라 소급해 안내하지 않아요. 내용이 달랐다는 뜻은 아니니, 법제처 연혁 법령에서 당시 판본과 부칙을 확인해 주세요.')
    if '계약당사자가 지방자치단체인지' in reasons:
        return ('계약당사자 확인 자료', '계약당사자가 지방자치단체로 확인되지 않으면 지방계약법을 대신 적용하지 않아요. 국가기관 계약이면 국가를 당사자로 하는 계약에 관한 법률과 소속 기관 계약 담당자를 확인해 주세요.')
    if '적용 신분 표현' in reasons:
        return ('적용 신분 정보', '국가공무원인지 지방공무원인지 다시 알려주세요. 신분 표현이 불분명하면 어느 기준도 임의로 적용하지 않아요.')
    return None


def needed(query):
    q=re.sub(r'\s+','',query)
    roles=personnel_scope.analyze(query)['roles']
    if 'public_worker' in roles and 'teacher' not in roles and '공무원' not in q:
        return ('공무직·기간제 근로 기준 자료', '공무직·무기계약직·기간제 근로자에게는 공무원 복무규정을 그대로 적용하지 않아요. 소속 기관의 취업규칙·근로계약과 근로기준법을 확인해 주세요.')
    if leave_situations.health_work(query):
        return ('건강검진 업무 자료', '건강검진의 예산·계약·비용·채용 서류·결과 처리 기준은 공무담에 등록되어 있지 않아요. 소속 기관 담당자와 관련 지침을 확인해 주세요. 본인이 검진을 받는 복무처리를 물으신다면 ‘건강검진 공가’로 다시 물어보세요.')
    if '예산' in q and any(w in q for w in ('잔액','집행률','얼마남','남은예산')):
        return ('부서 예산·집행 내역', '기관의 해당 연도 예산 배정액과 기준일별 집행 내역이 필요해요. 규정만으로 실제 잔액이나 집행률을 알 수는 없어요.')
    if '예산' in q and any(w in q for w in ('요구서','제출마감','편성일정')):
        return ('기관 예산 편성 안내', '기관의 해당 연도 예산 요구 공문·서식·제출 일정을 확인해 주세요.')
    if any(w in q for w in ('재고','배부현황','배부내역')):
        return ('물품 재고·배부 내역', '기관의 최신 물품대장과 입출고·배부 내역, 조회 기준일이 필요해요.')
    if any(w in q for w in ('프린터','복사기','노트북','컴퓨터')) and any(w in q for w in ('고장','수리요청','수리를요청','반납')):
        return ('기관 물품 관리 안내', '기관의 물품 관리 담당·수리 연락처 또는 반납 서식·인계 절차 자료를 확인해 주세요.')
    if '출장복명' in q or ('출장' in q and '결과보고' in q):
        return ('기관 출장 결과보고 기준', '출장복명서의 제출 기한·서식을 확인할 기관 복무 지침이 필요해요. 여비 정산 기한을 결과보고 기한으로 대신 안내하지 않아요.')
    if any(w in q for w in ('주간보고','의회요구','요구자료','미회신','사무전결','최종결재권자')):
        return ('기관 보고·업무분장 자료', '기관의 요청 공문·회신 현황·업무분장 또는 사무전결 규칙이 필요해요. 실제 담당자와 내부 마감은 기관 자료에서 확인해야 해요.')
    if '교육' in q and any(w in q for w in ('희망자','신청','회신','의무교육','승인','보고서','제출서류')):
        return ('기관 교육 안내·회신 자료', '기관의 교육 안내 공문·회신 서식·대상 부서·마감과 현재 회신 내역이 필요해요. 의무교육 종류·시간이나 승인 절차는 해당 교육 지침에서 확인해 주세요.')
    return None
