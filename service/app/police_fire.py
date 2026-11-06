"""Offline routing for 경찰·소방공무원의 휴직·징계·휴가 종류.

경찰공무원법 and 소방공무원법 are special provisions over 국가공무원법, and each service
decree falls back to 국가공무원 복무규정, so the national classifiers read the question and
the answer uses that body's rule: the national text plus the body's own exceptions.
공가 사유 and 연가 일수 keep their existing route, and so do questions about procedure.
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
    plan = absence.classify(national)
    if plan and plan['topics'] == ['absence']:
        return absence_plan(plan, key, body)
    plan = service_kinds.classify(national)
    if plan and plan['topics'] == ['discipline']:
        return dict(plan, rules=[f'discipline-{key}'], title=plan.get('title') or DISCIPLINE_TITLE.format(body=body))
    plan = leave_types.classify(national)
    if plan and plan['topics'] == ['leave_types']:
        return dict(plan, rules=[f'leave-types-{key}'], title=LEAVE_TITLES[key])
    return None
