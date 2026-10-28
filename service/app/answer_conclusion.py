"""Lead with an already-supported answer, without changing retrieval or rules.

Only reviewed summaries are reordered. The full selected sentence (including
conditions) and its citation stay together; no language model is required.
"""
from copy import deepcopy
import re


def lead(query, tree):
    if tree.get('kind') != 'summary':
        return tree
    rid = tree.get('rule_id', '')
    q = re.sub(r'\s+', '', query.split('\n업무환경:')[0])
    needle = None
    if rid == 'daily-car': needle = '일비의 절반'
    elif rid == 'local-trip': needle = '4시간 이상이면'
    elif rid == 'settlement': needle = '2주 안에'
    elif rid == 'additional-settlement': needle = '국외는' if '국외' in q else '국내는'
    elif rid in ('sick-leave', 'service-v70-sick'):
        needle = '진단서' if '진단서' in q or '6일' in q else ('일반 병가' if '며칠' in q or '일수' in q else '직무를 수행')
    elif rid == 'service-v70-side_job': needle = '사전 허가'
    elif rid == 'blood-leave': needle = '혈액관리법'
    elif rid == 'extended-occasion': needle = ''
    elif rid == 'extended-goods_quote': needle = '2인 이상'
    elif rid == 'extended-goods_payment_deadline': needle = '원칙은 검사 완료'
    elif rid == 'extended-goods_inspection_deadline': needle = '원칙은 이행 완료'
    elif rid == 'extended-goods_inspection_limit': needle = '3천만원 미만'
    elif rid == 'office:documents-receipt':
        needle = '당직근무자' if '당직' in q else ('관련성이 가장 높은' if any(t in q for t in ('여러부서','다부서')) else '문서과가 받았다면')
    elif rid == 'office:documents-drafting':
        needle = '직무를 대리하는' if any(t in q for t in ('대결','결재권자')) and any(t in q for t in ('없','부재','출장','휴가','대결')) else ('검토를 생략' if '검토' in q and '출장' in q else '결재를 받기 전에')
    elif rid.startswith('office:goods-'):
        if rid.endswith('-inventory'): needle = '정기재물조사는'
        elif rid.endswith('-disposal'): needle = '불용결정'
        elif rid.endswith('-sale'): needle = '일반입찰이 원칙'
        elif rid.endswith('-ledger'): needle = '장부'
    if needle is None:
        return tree
    # A title can only be promoted from a validated, cited summary item.
    for bi, branch in enumerate(tree.get('branches', [])):
        for ii, item in enumerate(branch.get('items', [])):
            if needle not in item.get('text', '') or not item.get('ref') or not item.get('support_quotes'):
                continue
            result = deepcopy(tree)
            selected_branch = result['branches'].pop(bi)
            selected = selected_branch['items'].pop(ii)
            selected_branch['items'].insert(0, selected)
            result['branches'].insert(0, selected_branch)
            result['title'] = selected['text']
            return result
    return tree
