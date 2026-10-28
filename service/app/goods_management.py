"""Narrow, offline routing for reviewed movable-goods administration.

The owner/administrative body determines the law. A personnel profile (for
example a national-status firefighter) alone does not establish that owner.
"""
import re


def classify(query):
    q = re.sub(r'\s+', '', query.split('\n업무환경:')[0])
    inventory = any(t in q for t in ('재물조사', '물품실사', '비품실사'))
    ledger = bool(re.search(r'(?:물품|비품|자산).{0,5}대장', q))
    disposal = '불용' in q or (any(t in q for t in ('물품', '비품', '컴퓨터', '책상', '의자')) and
                              any(t in q for t in ('폐기', '버려', '처분', '매각')))
    if not (inventory or ledger or disposal):
        return None
    plan = dict(topics=['goods_management'], rules=[])

    def unavailable(reason):
        return dict(plan, rules=['unsupported'], reason=reason)

    private = any(t in q for t in ('공기업', '공단', '공사직원', '공사소유', '민간기업', '사기업', '사립', '공공기관'))
    local = any(t in q for t in ('지자체', '지방자치단체', '시청', '군청', '구청', '도청', '공유재산및물품관리법'))
    national = any(t in q for t in ('국가기관', '중앙부처', '국가소유', '정부부처')) or (
        '물품관리법' in q and '공유재산및물품관리법' not in q)
    if private or local == national:
        return unavailable('물품을 관리하는 곳이 국가기관인지, 지방자치단체인지, 별도 공기업·공공기관인지 알려주세요. '
                           '직원의 국가직·지방직 신분만으로 물품 소유·관리 기준을 정하지 않아요. 공기업·공공기관은 자체 물품관리 규정도 필요해요.')
    scope = 'local' if local else 'national'
    if any(t in q for t in ('군수품', '도서', '박물관', '미술품', '소프트웨어', '리스', '동식물',
                            '압수', '몰수', '토지', '건물', '교육청', '학교', '보안삭제', '개인정보', '하드디스크')):
        return unavailable('이 물품은 특례·적용 제외 또는 별도 보안·재산 기준을 먼저 확인해야 해요. 일반 물품 절차만으로 처리하지 말고 해당 물품·기관의 규정을 등록해 주세요.')
    if any(t in q for t in ('우리재고', '남은수량', '담당자이름', '전화번호', '결재선', '실제목록', '우리기관마감',
                            '양식다운', '서식파일', '엑셀파일', '내구연한', '내용연수', '변상', '분실책임', '감가상각')):
        return unavailable('질문한 실제 물품 현황·담당자·서식 또는 세부 판단 자료는 아직 확인하지 못했어요. 기관 물품관리 규정·대장·해당 서식을 추가해 주세요.')
    if ledger and any(t in q for t in ('필수항목', '필수입력', '어떤항목', '필드', '열은', '칼럼')):
        return unavailable('대장에 입력할 정확한 항목은 적용되는 별지 서식 원문을 확인해야 해요. 현재는 관리·기록 의무 조문까지 등록되어 있고, 해당 기관의 실제 대장 서식은 추가 등록이 필요해요.')
    if ledger and local:
        return unavailable('지자체 물품대장의 종류·작성 방식·서식은 해당 시·군·구의 물품관리 조례·시행규칙과 별지를 확인해야 해요. 어느 지자체인지 알려주고 해당 자료를 등록해 주세요.')
    if disposal and national and any(t in q for t in ('매각', '입찰', '수의계약', '낙찰', '예정가격')):
        return unavailable('국가기관 불용품의 매각·입찰 세부 요건은 별도 조문 확인이 필요해요. 현재 등록한 국가기관 자료는 불용결정·폐기와 기록 절차까지예요.')
    kinds = []
    if inventory: kinds.append('inventory')
    if ledger: kinds.append('ledger')
    if disposal: kinds.append('sale' if local and any(t in q for t in ('매각','입찰','수의계약','낙찰','예정가격')) else 'disposal')
    plan['rules'] = [f'goods-{scope}-{kind}' for kind in kinds]
    return plan
