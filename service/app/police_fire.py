"""Offline routing for 경찰·소방공무원의 휴직·징계·휴가 종류.

경찰공무원법 and 소방공무원법 are special provisions over 국가공무원법, and each service
decree falls back to 국가공무원 복무규정, so the national classifiers read the question and
the answer uses that body's rule: the national text plus the body's own exceptions.
공가 사유 and 연가 일수 keep their existing route.

공무원 임용규칙 forms are not given to these bodies: neither their 임용령 nor 시행규칙 adopts that
예규, and both name no 휴직 신청서 or 복직원, so a procedure answer says who decides and sends the
form question to 인사부서. 임용규칙 제91조의10's 복무상황 보고 has no counterpart and stays unanswered.
"""
import re

BODY = re.compile(r'(?:해양)?(경찰|소방)(?:공무원|관)?(?:인데|입니다|이에요|이고)?')
# Other people working at these agencies, and subjects that only share the word.
ELSEWHERE = ('의무경찰', '의무소방', '일반직', '공무직', '기간제', '교원', '교사', '군인', '회사', '민간', '지방공무원', '국가공무원', '소방시설', '소방안전')
NAMES = {'경찰': ('police', '경찰공무원'), '소방': ('fire', '소방공무원')}
KINDS_TITLE = ('{body} 휴직 종류는 국가공무원법 제71조를 따라요. 질병·병역·생사불명·법률상 의무 수행·노조 전임은 임용권자가 명하고, '
               '고용·유학·연수·육아·가족돌봄·배우자 동반·자기개발은 본인이 원할 때 해요.')
SICK_TITLE = '질병휴직은 1년 이내(1년 연장 가능), 요양급여 대상이면 3년 이내(2년 연장 가능)이고, 법에 정한 직무 수행 중 공무상 질병·부상이면 5년 이내(3년 연장 가능)예요.'
MISSING_TITLE = '천재지변·전시 등으로 생사나 소재가 불명확해진 경찰공무원의 휴직은 법원의 실종선고를 받는 날까지예요.'
DISCIPLINE_TITLE = '{body} 징계도 국가공무원법에 따라 파면, 해임, 강등, 정직, 감봉, 견책 여섯 가지예요.'
LEAVE_TITLES = {'police': '경찰공무원 휴가도 국가공무원 복무규정에 따라 연가, 병가, 공가, 특별휴가 네 가지예요. 포상휴가는 1회 10일 이내로 따로 정해져 있어요.',
                'fire': '소방공무원 휴가도 국가공무원 복무규정을 준용해 연가, 병가, 공가, 특별휴가 네 가지예요. 포상휴가는 1회 10일 이내이고, 공가 사유와 시·도 소속의 특별휴가·장기재직휴가는 따로 정해져 있어요.'}
PROCEDURE_TITLE = '{body} 휴직은 임용권자가 명해요. {body} 임용령과 시행규칙에는 휴직 신청서 서식이 없으니 서식과 제출 서류는 소속 기관 인사부서에 확인하세요.'
KIND_TITLE = '{body} {kind}은 임용권자가 명해요. {body} 임용령과 시행규칙에는 신청서 서식과 제출 서류가 정해져 있지 않으니 소속 기관 인사부서에 확인하세요.'
RETURN_TITLE = '휴직 사유가 없어지면 30일 이내에 신고하고, 기간이 끝났으면 30일 이내에 복귀 신고를 하면 당연히 복직돼요.'
RETURN_FORM_TITLE = '{body} 임용령과 시행규칙에는 복직원 서식이 없어요. 소속 기관 인사부서에 확인하세요.'
EXTEND_TITLE = '공상 휴직을 같은 사유로 연장해 총 휴직 기간이 5년을 넘으면 임용심사위원회 의결을 거쳐요. 요양 승인 등을 받은 기간이 끝난 뒤에는 같은 사유로 새로 명하거나 연장할 수 없어요.'
EXTEND_ASK = re.compile(r'절차|어떻게|방법|신청|의결|심의')


def body_of(q, c):
    named = {m[1] for m in BODY.finditer(q)}
    if len(named) > 1:
        return None
    if named:
        return named.pop()
    in_context = {m[1] for m in BODY.finditer(c)}
    return in_context.pop() if len(in_context) == 1 else None


def absence_plan(plan, key, body):
    plan = dict(plan, rules=[f'absence-{key}'])
    only = plan.get('only')
    if not only:
        return plan
    plan['only'] = only + ['적용 법령']
    if '휴직 종류' in only:
        plan['title'] = KINDS_TITLE.format(body=body)
    elif '질병 휴직' in only:
        plan['title'] = SICK_TITLE
    elif '생사불명 휴직' in only and key == 'police':
        plan['title'] = MISSING_TITLE
    return plan


def procedure_plan(plan, key, body):
    """The national procedure plan names the kind asked about; this body's answer has no national forms."""
    only = plan['only']
    rule = dict(topics=['absence_procedure'], rules=[f'absence-procedure-{key}'])
    if only[0] == '휴직 중 보고':
        return None
    if only[-1] == '복직' and only[0] != '누가 명하나':
        title = RETURN_FORM_TITLE.format(body=body) if '복직원' in plan['title'] else RETURN_TITLE
        return dict(rule, only=['복직', '적용 법령'], title=title)
    if only[0] == '누가 명하나':
        return dict(rule, only=['누가 명하나', '복직', '적용 법령'], title=plan['title'])
    if only[0] == '종류별 신청 방법':
        return dict(rule, only=['누가 명하나', '신청서와 제출 서류', '인사발령 통지', '복직', '적용 법령'], title=PROCEDURE_TITLE.format(body=body))
    own = {'육아 휴직': ['육아 휴직'], '질병 휴직': ['공상 휴직 연장']}.get(only[0], [])
    return dict(rule, only=['누가 명하나', '신청서와 제출 서류'] + own + ['복직', '적용 법령'],
                title=KIND_TITLE.format(body=body, kind=only[0].replace(' ', '')))


def classify(query):
    from . import absence, leave_types, service_kinds
    question, _, context = query.partition('\n업무환경:')
    q = re.sub(r'\s+', '', question)
    c = re.sub(r'\s+', '', context)
    if any(t in q for t in ELSEWHERE) or any(t in c for t in ELSEWHERE if t not in ('지방공무원', '국가공무원')):
        return None
    word = body_of(q, c)
    if not word:
        return None
    key, body = NAMES[word]
    # The national classifiers read the question with the body taken out.
    national = BODY.sub('', q).replace('공상', '공무상') + '\n업무환경:국가공무원'
    # 경찰공무원 임용령 제2조의2 leaves out 해양경찰청 소속, and the procedure answer is read from it.
    coast_guard = '해양' in q + c
    if not coast_guard and '휴직' in q and '연장' in q and ('공상' in q or '공무상' in q) and EXTEND_ASK.search(q):
        return dict(topics=['absence_procedure'], rules=[f'absence-procedure-{key}'], only=['공상 휴직 연장', '적용 법령'], title=EXTEND_TITLE)
    plan = absence.classify(national)
    if plan and plan['topics'] == ['absence_procedure']:
        return None if coast_guard else procedure_plan(plan, key, body)
    if plan and plan['topics'] == ['absence']:
        return absence_plan(plan, key, body)
    plan = service_kinds.classify(national)
    if plan and plan['topics'] == ['discipline']:
        return dict(plan, rules=[f'discipline-{key}'], title=plan.get('title') or DISCIPLINE_TITLE.format(body=body))
    plan = leave_types.classify(national)
    if plan and plan['topics'] == ['leave_types']:
        return dict(plan, rules=[f'leave-types-{key}'], title=LEAVE_TITLES[key])
    return None
