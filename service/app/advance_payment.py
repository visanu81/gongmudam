"""Offline routing for 선금 (advance payment) questions: who may be paid, how much, by when.

A local government follows 지방회계법 제35조·시행령 제44조; a national agency
follows 국고금 관리법 제26조·시행령 제40조. Questions about paying before the
inspection keep the 지방계약법 제18조 answer. The 보증서·사용·정산·반환 steps
come from the 계약예규: 정부 입찰ㆍ계약 집행기준 제35~38조 and 지방자치단체
입찰 및 계약 집행기준 제1장 제2절.
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
        return dict(unavailable('국가기관인지 지방자치단체인지 알려주세요. 공사·제조·용역 계약 선금은 둘 다 계약금액의 70%까지이지만, '
                           '국가기관은 국고금 관리법 시행령 제40조(재정경제부장관 협의 시 100%), 지방자치단체는 지방회계법 시행령 제44조로 근거가 달라요.'), ask=True)
    side = 'local' if local else 'national'
    procedure = {'보증서': ('보증', '확약'), '사용과 정산': ('정산', '사용계획', '사용내역', '전용계좌', '배분'),
                 '반환 청구': ('반환', '돌려', '환수', '이자')}
    asked = [label for label, words in procedure.items() if any(t in q for t in words)]
    if asked:
        return dict(plan, rules=[f'advance-{side}-procedure'], lead=asked[0])
    plan['rules'] = [f'advance-{side}']
    if any(t in q for t in ('기한', '며칠', '언제', '이내', '청구')) and not any(t in q for t in ('얼마', '한도', '비율', '%', '퍼센트')):
        plan['lead'] = '지급 기한'
    elif any(t in q for t in ('대상', '경비', '임차료', '보조금', '정기간행물', '근거')) and not any(t in q for t in ('얼마', '한도', '비율')):
        plan['lead'] = '근거와 다른 선금 대상'
    return plan
