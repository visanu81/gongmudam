"""Offline office guidance: reviewed questions, complete articles, exact support.

The data map is a navigation aid. Only the saved official text supports answers;
neither model output nor an inferred graph edge can establish a legal rule.
"""
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit
import hashlib
import json
import re
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

BASE = Path(__file__).resolve().parents[1] / 'reference_data/office-20261025'
EXTRA_BASE = Path(__file__).resolve().parents[1] / 'reference_data/office-extra-20261025'
DOCUMENT_BASE = Path(__file__).resolve().parents[1] / 'reference_data/office-documents-20261026'
GOODS_BASE = Path(__file__).resolve().parents[1] / 'reference_data/office-goods-20261026'
CONTRACT_BASE = Path(__file__).resolve().parents[1] / 'reference_data/office-contract-20261104'
EXPENSE_BASE = Path(__file__).resolve().parents[1] / 'reference_data/office-expense-20261104'
NATIONAL_CONTRACT_BASE = Path(__file__).resolve().parents[1] / 'reference_data/office-national-contract-20261104'
ADVANCE_BASE = Path(__file__).resolve().parents[1] / 'reference_data/office-advance-20261104'
ADVANCE_RULE_BASE = Path(__file__).resolve().parents[1] / 'reference_data/office-advance-rule-20261104'
LEAVE_TYPES_BASE = Path(__file__).resolve().parents[1] / 'reference_data/office-leave-types-20261105'
ABSENCE_BASE = Path(__file__).resolve().parents[1] / 'reference_data/office-absence-20261105'
COLLECTIONS = frozenset({'office-20261025', 'office-extra-20261025', 'office-documents-20261026', 'office-goods-20261026',
                         'office-contract-20261104', 'office-expense-20261104',
                         'office-national-contract-20261104', 'office-advance-20261104',
                         'office-advance-rule-20261104', 'office-leave-types-20261105',
                         'office-absence-20261105'})
_COLLECTION_ROOTS = {
    'office-20261025': 'BASE',
    'office-extra-20261025': 'EXTRA_BASE',
    'office-documents-20261026': 'DOCUMENT_BASE',
    'office-goods-20261026': 'GOODS_BASE',
    'office-contract-20261104': 'CONTRACT_BASE',
    'office-expense-20261104': 'EXPENSE_BASE',
    'office-national-contract-20261104': 'NATIONAL_CONTRACT_BASE',
    'office-advance-20261104': 'ADVANCE_BASE',
    'office-advance-rule-20261104': 'ADVANCE_RULE_BASE',
    'office-leave-types-20261105': 'LEAVE_TYPES_BASE',
    'office-absence-20261105': 'ABSENCE_BASE',
}
router = APIRouter(prefix='/api/office-sources', tags=['서무 공통 근거'])
LABELS = {'privacy': '개인정보 처리', 'records': '기록물 관리',
          'disclosure': '정보공개 처리', 'handover': '업무 인수인계',
          'documents': '공문 접수·기안·결재',
          'goods_management': '물품대장·재물조사·불용 처리',
          'contract': '수의계약 금액·사유',
          'expense': '업무추진비 집행내역 공개',
          'national_contract': '국가기관 계약 견적·검사·대가 지급',
          'advance': '선금 지급 대상·한도·기한',
          'leave_types': '공무원 휴가 종류',
          'absence': '공무원 휴직'}


def flat(value):
    return re.sub(r'\s+', '', value)


def pack_root(collection):
    if collection not in COLLECTIONS:
        return None
    return globals()[_COLLECTION_ROOTS[collection]]


def load(name):
    rows=[]
    for collection in _COLLECTION_ROOTS:
        root = pack_root(collection)
        try:
            rows.extend(json.loads((root/name).read_text(encoding='utf-8')))
        except (OSError,ValueError):
            continue
    return rows


def asset(folder, name):
    if not isinstance(name, str) or Path(name).name != name or '\\' in name or ':' in name:
        raise ValueError('Invalid office source asset')
    return folder / name


def metadata(sha):
    try:
        row = next((r for r in load('manifest.json') if r['sha256'] == sha), None)
        if not row:
            return None
        root = pack_root(row.get('collection'))
        if root is None:
            return None
        url = urlsplit(row['source_url'])
        # The 집행지침 is published by 기획예산처, not on law.go.kr.
        if url.scheme != 'https' or url.hostname not in {'law.go.kr', 'www.law.go.kr', 'mpb.go.kr', 'www.mpb.go.kr'}:
            return None
        # A document-viewer source is saved as several page files.
        raws = zip(row['raw_files'], row['raw_sha256s']) if 'raw_files' in row else [(row['raw_file'], row['raw_sha256'])]
        for folder, name, expected in [('excerpts', row['filename'], sha)] + [('raw', n, d) for n, d in raws]:
            if hashlib.sha256(asset(root / folder, name).read_bytes()).hexdigest() != expected:
                return None
        return row
    except (OSError, ValueError, KeyError, TypeError):
        return None


@router.get('/{sha}/original')
def original(sha: str):
    row = metadata(sha)
    if not row:
        raise HTTPException(404, '보관 원문의 해시를 확인하지 못했습니다.')
    # Serve text, never execute downloaded official HTML in the app origin.
    root = pack_root(row.get('collection'))
    if root is None:
        raise HTTPException(404, '보관 원문의 해시를 확인하지 못했습니다.')
    text = asset(root / 'excerpts', row['filename']).read_text(encoding='utf-8')
    return PlainTextResponse(row['title'] + ' ' + row['article'] + '\n' + row['source_url'] + '\n\n' + text,
                             headers={'Cache-Control': 'no-store'})


def classify(query):
    q = flat(query)
    delete_request=bool(re.search(r'삭제(?:를|을)?(?:요구|요청|해달)',q))
    stop_request=bool(re.search(r'처리(?:를|의)?정지|동의(?:를)?철회',q))
    rights=delete_request or stop_request or any(t in q for t in ('열람','정정'))
    repeated_disclosure=bool(re.search(r'반복.{0,12}청구|청구.{0,12}반복|재청구|같은내용.{0,8}청구|동일한.{0,8}청구',q))
    rules = []
    topics = []
    if any(t in q for t in ('정보공개', '공개청구')):
        topics.append('disclosure')
        if any(t in q for t in ('수수료','비용부담','감면','면제','우편요금')):
            rules.append('disclosure-fees')
        elif repeated_disclosure or any(t in q for t in ('반복요청','동일청구','종결')):
            rules.append('disclosure-repeat')
        elif any(t in q for t in ('제3자', '제삼자')) and any(t in q for t in ('이의신청', '불복', '공개반대', '비공개요청')):
            rules.append('disclosure-third-objection')
        elif any(t in q for t in ('이의신청', '불복')):
            rules.append('disclosure-objection')
        elif any(t in q for t in ('개인정보', '부분공개', '가려', '가리', '비공개')):
            rules.append('disclosure-partial')
        elif any(t in q for t in ('다른기관', '타기관', '소관', '이송', '보유하지')):
            rules.append('disclosure-transfer')
        elif any(t in q for t in ('제3자', '당사자', '관련자')):
            rules.append('disclosure-third-party')
        elif any(t in q for t in ('기한','기간','며칠','언제','절차','방법','처리','결정','회신','답','어떻게','연장')):
            rules.append('disclosure-deadline')
        else:
            rules.append('unsupported')
        if rules[0] in {'disclosure-partial','disclosure-transfer','disclosure-third-party'} and any(
                t in q for t in ('기한','며칠','결정기간','결정기한','언제까지','연장')):
            rules.append('disclosure-deadline')
    from . import knowledge_relevance
    privacy = knowledge_relevance.evidence_context(query) == 'privacy'
    roster = any(t in q for t in ('명단', '참석자', '희망자', '교육생'))
    roster_contact = any(t in q for t in ('연락처', '전화번호', '휴대전화'))
    privacy = privacy or roster and any(t in q for t in ('연락처', '전화번호', '휴대전화', '건강정보', '다른기관', '외부에', '보내', '보냈', '삭제', '지워', '파기', '버려'))
    # A participant's contact deletion is a data-subject request; deleting a
    # completed attendee list by itself remains an ordinary records question.
    privacy = privacy or '참가자' in q and roster_contact and rights
    # Child-application consent questions can omit the word 개인정보. Keep
    # this narrow so childcare leave and other child topics stay on their own path.
    privacy = privacy or (any(t in q for t in ('만14세미만', '14세미만', '아동')) and
                          any(t in q for t in ('정보', '자료')) and '동의' in q)
    privacy = privacy or any(t in q for t in ('민감정보', '건강정보', '병력')) and any(t in q for t in ('수집', '동의', '처리', '제공'))
    # Disclosure masking is answered under its own law, not by an unrelated
    # blanket statement that every personal-information disclosure is forbidden.
    if privacy and 'disclosure' not in topics:
        topics.append('privacy')
        if any(t in q for t in ('유출', '해킹', '분실', '잘못보냈', '오발송')):
            rules.append('privacy-leak')
        else:
            matched=[]
            outsourced=any(t in q for t in ('수탁','위탁'))
            if any(t in q for t in ('만14세','14세미만','아동','법정대리인')):
                matched.append('privacy-child')
            if '열람' in q:matched.append('privacy-access')
            if delete_request or '정정' in q:matched.append('privacy-rectify')
            if stop_request:matched.append('privacy-stop')
            if outsourced:matched.append('privacy-outsource')
            if any(t in q for t in ('민감정보','병력','건강정보')):
                matched.append('privacy-sensitive')
            if any(t in q for t in ('주민등록번호','주민번호','고유식별')):
                matched.append('privacy-rrn' if '고유식별' not in q else 'unsupported')
            if not rights and any(t in q for t in ('파기','삭제','지워','지우','버려','보관','보유기간','보존기간','끝났')):
                matched.append('privacy-delete')
            if (not outsourced or any(t in q for t in ('제3자제공과','제3자제공의차이','제3자제공차이'))) and any(t in q for t in ('다른기관','외부','제3자','목적외','전송','보내','보냈','제공','마스킹','가려','가리')):
                matched.append('privacy-share')
            if any(t in q for t in ('접근권한','암호','보안','안전조치')):
                matched.append('privacy-security')
            if not matched and any(t in q for t in ('수집','받아','받으면','전화번호','연락처','동의','필요한항목','명단작성','명단만들')):
                matched.append('privacy-collect')
            rules.extend(matched or ['unsupported'])
    record = any(t in q for t in ('기록물', '회의록', '공문보관')) or (
        any(t in q for t in ('이메일', '전자우편', '메일', '메신저')) and any(t in q for t in ('등록', '기록', '보관', '보존')))
    if record:
        topics.append('records')
        if any(t in q for t in ('등록정보','등록번호')) and any(t in q for t in ('수정','삭제','변경','정정','고쳐')):
            rules.append('records-register-detail')
        elif any(t in q for t in ('폐기', '삭제', '지워', '지우', '버려', '파기')):
            rules.append('records-disposal-detail' if any(t in q for t in ('절차','평가','심사','심의','재난','소실','의견조회')) else 'records-disposal')
        elif any(t in q for t in ('회의록', '회의기록')):
            rules.append('records-meeting-detail' if any(t in q for t in ('대상','어떤회의','작성항목','참석자','작성방법','어떤내용')) else 'records-meeting')
        elif any(t in q for t in ('보존기간', '이관', '몇년', '얼마나')):
            rules.append('records-retention-detail' if any(t in q for t in ('기준','정하','책정','분류','기산','종류')) else 'records-retention')
        else:
            rules.append('records-register-detail' if any(t in q for t in ('등록절차','등록번호','수정이력')) else 'records-register')
    if any(t in q for t in ('인수인계', '인계인수', '업무인계', '업무인수', '업무편람', '후임자', '전임자')):
        topics.append('handover')
        rules.append('handover-manual' if '업무편람' in q else 'handover-checklist')
    # General official-document workflow is distinct from a leave/travel
    # approval in e-사람, records retention, and disclosure processing.
    named_counterapproval = '대결' in q and '결재권자' in q and not any(
        t in q for t in ('여행비계산', '여비계산', '출장여비', '출장비계산', '휴가신청', '출장신청')) and not re.search(
            r'e[-·]?사람|이사람|스마트출장', q)
    document = named_counterapproval or any(t in q for t in ('공문', '기안문', '시행문')) or bool(
        re.search(r'문서(?:의)?(?:접수|배부|기안|검토|결재)|기안.{0,15}(?:검토|결재)', q))
    if document and not topics:
        topics.append('documents')
        receipt = any(t in q for t in ('접수', '배부', '문서과', '처리과', '당직'))
        drafting = any(t in q for t in ('기안', '검토', '협조', '결재', '전결', '대결', '시행문', '발신'))
        if receipt: rules.append('documents-receipt')
        if drafting: rules.append('documents-drafting')
        # Do not let a familiar word such as 공문 answer a new, unsupported
        # subject or pretend to know an institution's people, menus or route.
        unknown = ('저작권', '글꼴', '폰트', '글자크기', '맞춤법', '비밀문서', '보안등급',
                   '민원처리', '결재선', '담당자이름', '담당자연락처',
                   '몇번메뉴', '버튼', '클릭', '온나라', '서식다운', '양식다운', '양식파일')
        generic_recipient_question = any(t in q for t in ('누구', '어느부서'))
        institution_specific = any(t in q for t in ('우리', '저희', '기관명', '담당자는', '담당자에게')) or bool(
            re.search(r'(?:서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주).{0,8}(?:시청|도청|구청|군청|교육청)', q))
        if (not rules or any(t in q for t in unknown) or
                generic_recipient_question and (not receipt or institution_specific)):
            rules = ['unsupported']
    if not topics:
        from .absence import classify as classify_absence
        absence = classify_absence(query)
        if absence:
            return absence
        from .leave_types import classify as classify_leave_types
        leave_types = classify_leave_types(query)
        if leave_types:
            return leave_types
        from .advance_payment import classify as classify_advance
        advance = classify_advance(query)
        if advance:
            return advance
        from .goods_management import classify as classify_goods
        goods = classify_goods(query)
        if goods:
            return goods
        from .contract_rules import classify as classify_contract
        contract = classify_contract(query)
        if contract:
            return contract
        from .expense_disclosure import classify as classify_expense
        expense = classify_expense(query)
        if expense:
            return expense
        from .national_contract import classify as classify_national_contract
        national_contract = classify_national_contract(query)
        if national_contract:
            return national_contract
    if not topics:
        return None
    unsupported = ('과태료','과징금','징역','벌금','손해배상','징계','해외법','GDPR')
    if 'privacy' in topics:
        unsupported += ('전송요구','국외이전','가명정보','익명처리','자동화','CCTV','영상정보','생체','지문')
        if 'privacy-child' not in rules:unsupported+=('미성년',)
        if (rights or stop_request) and any(t in q for t in ('며칠','기한','몇일')):
            rules=['unsupported']
    if 'disclosure' in topics:
        unsupported += ('행정심판방법','행정소송방법')
        if any(t in q for t in ('개인정보열람','개인정보정정','개인정보처리정지')):
            rules=['unsupported']
    if 'records' in topics and any(t in q for t in ('재난','수침','소실','멸실')):
        rules=['unsupported']
    if any(t in q for t in unsupported):
        rules = ['unsupported']
    return dict(topics=list(dict.fromkeys(topics)), rules=list(dict.fromkeys(rules)))


def documents(query, docs, today):
    plan = classify(query)
    registered = [d for d in docs if (d.get('official') or {}).get('collection') in COLLECTIONS]
    if not plan:
        return None
    if not registered:
        if 'goods_management' in plan['topics']:
            return [], plan.get('reason') or '물품관리 원문 자료가 아직 등록되지 않았어요. 해당 국가·지자체 자료를 등록해 주세요.', plan
        if 'contract' in plan['topics']:
            return [], plan.get('reason') or '수의계약 조문(국가계약법 시행령 제26조·지방계약법 시행령 제25조)이 아직 등록되지 않았어요.', plan
        if 'national_contract' in plan['topics'] and plan.get('reason'):
            return [], plan['reason'], plan
        if 'absence' in plan['topics']:
            return [], '휴직 조문(국가공무원법 제71~73조·지방공무원법 제63~65조)이 아직 등록되지 않았어요.', plan
        if 'leave_types' in plan['topics']:
            return [], '휴가의 종류를 정한 조문(국가공무원 복무규정 제14조·지방공무원 복무규정 제6조)이 아직 등록되지 않았어요.', plan
        if 'advance' in plan['topics']:
            return [], plan.get('reason') or '선금 지급 조문(지방회계법 시행령 제44조·국고금 관리법 시행령 제40조)이 아직 등록되지 않았어요.', plan
        if 'expense' in plan['topics']:
            return [], plan.get('reason') or '업무추진비 공개 기준(지방회계관리훈령 제121조·별표 2의2, 국가 예산 집행지침)이 아직 등록되지 않았어요.', plan
        return None
    if plan.get('reason'):
        return [], plan['reason'], plan
    if 'unsupported' in plan['rules']:
        return [], '질문한 세부 판단에 필요한 조문·시행령 또는 전문 검토 자료가 아직 없습니다.', plan
    q = flat(query)
    if 'handover' in plan['topics'] and any(t in q for t in ('공기업', '공공기관', '민간기업', '사기업')):
        return [], '이번 인수인계 자료는 행정기관 규정입니다. 해당 공공기관·기업의 인계인수 규정이 필요합니다.', plan
    if 'documents' in plan['topics'] and any(t in q for t in ('공기업', '공공기관', '민간기업', '사기업', '개인회사', '대학교', '사립학교')):
        return [], '이번 공문 처리 자료는 행정기관 기준입니다. 해당 조직의 적용 여부와 문서관리·사무전결 규정을 확인해 주세요.', plan
    if set(plan['topics']) & {'records','disclosure'} and any(t in q for t in ('민간기업','사기업','개인회사')):
        return [], '이번 자료는 해당 법 적용대상 공공기관 기준입니다. 질문한 기관의 적용 여부와 별도 기준을 확인해야 합니다.', plan
    catalog = {r['id']: r for r in load('questions.json')}
    if any(key not in catalog for key in plan['rules']):
        return [], '질문에 맞는 검토된 답변 자료가 아직 없습니다.', plan
    needed = {key for rid in plan['rules'] for key in catalog[rid]['sources']}
    dates = []
    for y, m, d in re.findall(r'(20\d{2})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})(?:일)?', query):
        try:
            dates.append(date(int(y), int(m), int(d)))
        except ValueError:
            return [], '질문한 날짜를 확인해 주세요.', plan
    years={int(y) for y in re.findall(r'(20\d{2})\s*년', query)}
    if any(d > today for d in dates) or any(y > today.year for y in years):
        return [], '미래 시점의 적용 판본은 아직 확인하지 않았습니다.', plan
    valid = {}
    for d in registered:
        canonical=(d.get('official') or {}).get('id')
        if canonical not in needed or not d['enabled'] or not d['current']:
            continue
        info = d['official']
        if metadata(d['sha256']) != info or info['effective_date'] > today.isoformat():
            continue
        if any(day.isoformat() < info['effective_date'] for day in dates):
            continue
        if any(y<int(info['effective_date'][:4]) for y in years):
            continue
        valid.setdefault(canonical,d)
    if set(valid) != needed:
        return [], '필요한 원문이 없거나 사용 제외·변경·적용 시점 차이가 있습니다. 해당 판본을 확인해 주세요.', plan
    order = {sid: n for n, sid in enumerate(key for rid in plan['rules'] for key in catalog[rid]['sources'])}
    result=sorted(valid.values(),key=lambda d: order[d['official']['id']])
    return result, '', plan


def summary(query, reply):
    plan = reply.get('office_plan')
    if not plan or not reply.get('evidence'):
        return None
    catalog = {r['id']: r for r in load('questions.json')}
    evidence = reply['evidence']
    branches = []
    for rid in plan['rules']:
        rule = catalog.get(rid)
        if not rule:
            return None
        for branch in rule['branches']:
            items = []
            for item in branch['items']:
                ref = next((i for i, h in enumerate(evidence, 1) if (h.get('official') or {}).get('id') == item['source']), None)
                if not ref:
                    return None
                hit = evidence[ref - 1]
                if not metadata(hit['sha256']):
                    return None
                quotes = []
                for anchor in item['requires']:
                    match = re.search(r'\s*'.join(map(re.escape, flat(anchor))), hit['text'])
                    if not match:
                        return None
                    quotes.append(match[0])
                if not quotes:
                    return None
                items.append(dict(text=item['text'], ref=ref, support_quotes=quotes))
            branches.append(dict(label=branch['label'], items=items))
    # A question about one kind shows that kind, not every other kind in the law.
    if plan.get('only'):
        branches = [b for name in plan['only'] for b in branches if b['label'] == name]
    # The branch the question asks about comes first, as the conclusion.
    if plan.get('lead'):
        branches.sort(key=lambda b: b['label'] != plan['lead'])
    title = ' · '.join(LABELS[t] for t in plan['topics']) + ' — 먼저 확인할 내용'
    # These topics answer one question, so its first sentence is the conclusion.
    if set(plan['topics']) & {'absence', 'leave_types'}:
        title = branches[0]['items'][0]['text'].split(' 근거는 ')[0]
    return dict(kind='summary', title=title,
                rule_id='office:' + '+'.join(plan['rules']), branches=branches,
                reviewed_source_sha256s=[h['sha256'] for h in evidence],
                note='보관한 공식 조문의 확인된 요약입니다. 기관별 서식·보존기간·담당자 절차는 추가 확인하고, 최신 확인일과 시행일은 원문에서 확인하세요.')
