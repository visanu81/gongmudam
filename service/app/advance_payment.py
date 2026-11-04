"""Offline routing for 선금 (advance payment) questions: who may be paid, how much, by when.

A local government follows 지방회계법 제35조·시행령 제44조; a national agency
follows 국고금 관리법 제26조·시행령 제40조. Questions about paying before the
inspection keep the 지방계약법 제18조 answer, and the 보증서·정산 procedure in
the 계약예규 is not registered, so it is named instead of guessed.
"""
import re

LOCAL = ('지자체', '지방자치단체', '시청', '군청', '구청', '도청', '지방계약법', '지방회계법')
NATIONAL = ('국가기관', '중앙부처', '중앙행정기관', '정부부처', '국가계약법', '국고금')


def classify(query):
    question, _, context = query.partition('\n업무환경:')
    q = re.sub(r'\s+', '', question); c = re.sub(r'\s+', '', context)
    if not any(t in q for t in ('선금', '선급')) or '검사' in q:
        return None
    plan = dict(topics=['advance'], rules=[])

    def unavailable(reason):
        return dict(plan, rules=['unsupported'], reason=reason)

    if any(t in q for t in ('공기업', '공단', '공공기관', '민간', '사기업')):
        return unavailable('공기업·공공기관·민간은 자체 계약·회계 규정의 선금 기준을 따로 확인해야 해요. 해당 기관의 규정을 등록해 주세요.')
    local = any(t in q for t in LOCAL)
    national = any(t in q for t in NATIONAL)
    if local == national:
        local, national = '지방공무원' in c, '국가공무원' in c
    if local == national:
        return unavailable('국가기관인지 지방자치단체인지 알려주세요. 공사·제조·용역 계약 선금은 둘 다 계약금액의 70%까지이지만, '
                           '국가기관은 국고금 관리법 시행령 제40조(재정경제부장관 협의 시 100%), 지방자치단체는 지방회계법 시행령 제44조로 근거가 달라요.')
    if any(t in q for t in ('보증', '정산', '반환', '공제', '사용계획', '전용계좌', '이자')):
        rule = '선금지급 요령(재정경제부 계약예규)' if national else '「지방자치단체 입찰 및 계약 집행기준」 제6장 선금·대가 지급요령(행정안전부 예규)'
        return unavailable(f'선금 보증서·사용계획·정산·반환 같은 세부 절차는 {rule}에 있는데 아직 등록되지 않았어요. '
                           '선금을 줄 수 있는 경비, 한도, 지급 기한은 바로 답할 수 있어요.')
    plan['rules'] = ['advance-local' if local else 'advance-national']
    if any(t in q for t in ('기한', '며칠', '언제', '이내', '청구')) and not any(t in q for t in ('얼마', '한도', '비율', '%', '퍼센트')):
        plan['lead'] = '지급 기한'
    elif any(t in q for t in ('대상', '경비', '임차료', '보조금', '정기간행물', '근거')) and not any(t in q for t in ('얼마', '한도', '비율')):
        plan['lead'] = '근거와 다른 선금 대상'
    return plan
