"""봉급·명절휴가비·정근수당·가족수당·직급보조비·초과근무수당 amounts from the official 2026 sources, without AI.

The answer search finds the articles; the amounts are in annex tables
(공무원보수규정 별표 3·10, 수당 규정 별표 2·5·14·15, the local 가족수당 in 제10조 itself,
and the 초과근무수당 지급단가 table of the national and local pay guidelines)
collected by tools/collect_pay_tables.py.
A question that names the grade, 호봉 or years of service gets the amount with the
formula and the annex it came from; a question missing them is told what to add.
Amounts are the table values before tax and deductions, never a payslip.
"""
from functools import lru_cache
from pathlib import Path
import hashlib, json, re

COLLECTION = 'pay-tables-2026'
BASE = Path(__file__).resolve().parents[1] / 'reference_data' / COLLECTION
AMOUNT = r'\d{1,3}(?:,\d{3})+'

GENERAL = ['1급', '2급', '3급', '4급', '5급', '6급', '7급', '8급', '9급']
# 별표 10 columns, highest first; each column is shared by a police and a fire rank.
POLICE_FIRE = [('치안정감', '소방정감'), ('치안감', '소방감'), ('경무관', '소방준감'), ('총경', '소방정'), ('경정', '소방령'),
               ('경감', '소방경'), ('경위', '소방위'), ('경사', '소방장'), ('경장', '소방교'), ('순경', '소방사')]
# 정근수당 가산금 for every public servant except the military (별표 2 제2호; the 5~10년 cell is merged,
# checked against the annex image on 2026-11-03), plus the 추가 가산금 in its 비고.
BONUS = [(20, 100_000), (15, 80_000), (10, 60_000), (5, 50_000), (0, 30_000)]
EXTRA = [(25, 30_000), (20, 10_000)]
ARTICLES = {
    'holiday': {'national': '공무원수당 등에 관한 규정 제18조의3(명절휴가비)', 'local': '지방공무원 수당 등에 관한 규정 제18조의3(명절휴가비)'},
    'longevity': {'national': '공무원수당 등에 관한 규정 제7조(정근수당)', 'local': '지방공무원 수당 등에 관한 규정 제6조(정근수당)'},
    'family': {'national': '공무원수당 등에 관한 규정 제10조(가족수당)', 'local': '지방공무원 수당 등에 관한 규정 제10조(가족수당)'},
    'subsidy': {'national': '공무원수당 등에 관한 규정 제18조의6(직급보조비)', 'local': '지방공무원 수당 등에 관한 규정 제18조의6(직급보조비)'},
}
# The row label each 직급보조비 amount follows in the annex text (spaces removed), 1급~9급 and
# the POLICE_FIRE columns; the local annex repeats 상당 in its 단체장 rows, so its labels run on.
SUBSIDY_LABELS = {
    'national': dict(general=['1급(상당)', '2급(상당)', '3급(상당)', '4급(상당)', '5급(상당)', '6급(상당)', '7급(상당)', '8ㆍ9급(상당)', '8ㆍ9급(상당)'],
                     police_fire=['치안정감,소방정감', '치안감,소방감', '경무관,소방준감', '총경,소방정', '경정,소방령',
                                  '경감ㆍ경위', '경감ㆍ경위', '경사,소방장', '경장ㆍ순경', '경장ㆍ순경']),
    'local': dict(general=['1급(상당),개방형', '2급(상당),연구관', '3급(상당),연구관', '4급(부단체장제외,상당)', '5급(상당),연구관',
                           '6급(상당),연구사', '7급(상당),일반임기제', '8ㆍ9급(상당),일반임기제', '8ㆍ9급(상당),일반임기제'],
                  deputy_4=['4급부단체장']),
}
ORDINAL = ['첫째', '둘째', '셋째', '넷째', '다섯째']
KOREAN_COUNT = {'한': 1, '하나': 1, '두': 2, '둘': 2, '세': 3, '셋': 3, '네': 4, '넷': 4, '다섯': 5}


def parse_salary(text):
    """Rows of a 봉급표 PDF: 호봉 → amount per column; a blank cell (U+3000) means no such 호봉."""
    columns = 10 if '치안정감' in text else 9
    rows = {}
    for line in text.splitlines():
        # Split on ASCII spaces only: str.split() and \s also treat the blank cell U+3000 as a separator.
        parts = [p for p in line.strip(' \t\r').split(' ') if p]
        if len(parts) < 2 or not re.fullmatch(r'\d{1,2}', parts[0]) or not all(re.fullmatch(AMOUNT, p) or p == '　' for p in parts[1:]):
            continue
        cells = parts[1:]
        if len(cells) != columns:
            raise ValueError(f'호봉 {parts[0]}: {len(cells)} cells, expected {columns}')
        rows[int(parts[0])] = [int(c.replace(',', '')) if c != '　' else None for c in cells]
    if sorted(rows) != list(range(1, max(rows) + 1)):
        raise ValueError('호봉 rows are not continuous')
    return dict(columns=GENERAL if columns == 9 else ['/'.join(p) for p in POLICE_FIRE], rows={str(k): v for k, v in rows.items()})


def parse_longevity(text):
    """정근수당 rates by years of service; the 가산금 amounts above must all appear in the annex."""
    flat = re.sub(r'\s', '', text)
    rates = [(int(y), kind, int(p)) for y, kind, p in re.findall(r'(\d{1,2})년(미만|이상)월봉급액의(\d{1,2})%', flat)]
    if len(rates) != 8 or rates[-1][1] != '이상':
        raise ValueError('정근수당 rates not found')
    for amount in [b for _, b in BONUS] + [e for _, e in EXTRA]:
        if f'{amount:,}원' not in flat:
            raise ValueError(f'가산금 {amount:,}원 not in the annex')
    under = sorted((y, p) for y, kind, p in rates if kind == '미만')
    return dict(under=under, at_least=[rates[-1][0], rates[-1][2]], bonus=BONUS, extra=EXTRA)


def parse_family(text):
    """가족수당 monthly amounts: 별표 5 writes 40,000원, the local 제10조 writes 월 4만원."""
    flat = re.sub(r'\s', '', text)
    if '지방공무원' in flat[:200] or '월4만원' in flat:
        won = lambda pattern: int(re.search(pattern + r'(\d+)만원', flat)[1]) * 10_000
        spouse, first, second, third, other = (won(p) for p in (r'배우자:월', r'첫째자녀:월', r'둘째자녀:월', r'셋째이후자녀:1명당월', r'부양가족:1명당월'))
    else:
        won = lambda pattern: int(re.search(pattern + rf'({AMOUNT})원', flat)[1].replace(',', ''))
        spouse, first, second, third, other = (won(p) for p in (r'배우자', r'첫째자녀', r'둘째자녀', r'셋째이후자녀', r'가족1명당'))
    return dict(spouse=spouse, other=other, children=[first, second, third])


def parse_subsidy(text):
    """직급보조비 by grade: the first amount after each row label in the annex."""
    flat = re.sub(r'\s', '', text)
    labels = SUBSIDY_LABELS['local' if '지방공무원수당' in flat[:100] else 'national']
    def amount(label):
        at = flat.find(label)
        if at < 0:
            raise ValueError('직급보조비 row not found: ' + label)
        return int(re.compile(rf'({AMOUNT})원').search(flat, at)[1].replace(',', ''))
    return {key: [amount(label) for label in row] for key, row in labels.items()}


def parse_overtime(text):
    """[별표2] 초과근무수당 지급단가: 시간외(시간당)·야간(시간당)·휴일(일당) for 5급~9급 and 경정~순경."""
    row = rf'\s+({AMOUNT})\s+({AMOUNT})\s+({AMOUNT})'
    def amounts(pattern):
        m = re.search(pattern + row, text)
        if not m:
            raise ValueError('초과근무수당 row not found: ' + pattern)
        return [int(v.replace(',', '')) for v in m.groups()[-3:]]
    result = dict(general={str(g): amounts(rf'(?<!\d){g}\s*급(?:\s*･\s*{6 - (g - 4)}등급)?') for g in range(5, 10)})
    if '경정' in text:
        result['police_fire'] = {str(i): amounts(rf'{police}\s*･\s*{fire}') for i, (police, fire) in enumerate(POLICE_FIRE) if i >= 4}
    return result


PARSERS = dict(salary=parse_salary, longevity=parse_longevity, family=parse_family, subsidy=parse_subsidy, overtime=parse_overtime)


@lru_cache(maxsize=1)
def load():
    """Tables and their sources; a raw annex whose hash changed is refused."""
    manifest = json.loads((BASE / 'manifest.json').read_text(encoding='utf-8'))
    for entry in manifest:
        if hashlib.sha256((BASE / 'raw' / entry['raw_file']).read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError('Pay annex changed: ' + entry['id'])
    tables = json.loads((BASE / 'tables.json').read_text(encoding='utf-8'))
    return {e['id']: e for e in manifest}, tables


def _source(entry):
    return {k: entry[k] for k in ('law', 'title', 'revised', 'applies', 'source_url', 'sha256')}


def _rank(question):
    """(table id, column, label) for the grade named in the question."""
    for i, (police, fire) in enumerate(POLICE_FIRE):
        for name in (fire, police):
            if re.search(rf'{name}(?!감|정감|준감)' if name in ('소방정', '소방감', '치안감') else name, question):
                return 'salary-police-fire', i, name
    m = re.search(r'(?<!\d)([1-9])\s*급', question)
    if m:
        return 'salary-general', int(m[1]) - 1, f'{m[1]}급'
    return None


def _years(question):
    m = re.search(r'(?:재직|근무|근속|경력|근무연수)\s*(?:기간)?\s*(\d{1,2})\s*년|(\d{1,2})\s*년\s*(?:이상\s*)?(?:재직|근무|근속)', question)
    return int(m[1] or m[2]) if m else None


def _count(question, pattern):
    """How many of the family named by pattern (자녀 2명, 아이 둘); 1 when named without a number, else 0."""
    m = re.search(rf'(?:{pattern})\s*(\d|하나|다섯|[한두세네둘셋넷])\s*(?:명|분)?', question)
    if m:
        return int(m[1]) if m[1].isdigit() else KOREAN_COUNT[m[1]]
    return 1 if re.search(pattern, question) else 0


def _family(question):
    """(spouse, children, other dependents) named in the question; other is None for 부모님 without a number."""
    spouse = 1 if re.search(r'배우자|아내|남편|와이프', question) else 0
    children = _count(question, r'자녀|아이') or _count(question, r'아들') + _count(question, r'딸')
    named = re.search(r'(?:부모님?|부양가족|직계존속)\s*(?:\d|하나|다섯|[한두세네둘셋넷])', question)
    if named:
        other = _count(question, r'부모님?|부양가족|직계존속')
    elif re.search(r'부모', question):
        other = None
    else:
        other = sum(_count(question, p) for p in ('어머니', '아버지', '장인', '장모'))
    return spouse, children, other


def _won(n):
    return f'{n:,}원'


def calculate(question, context=''):
    """Amounts for a pay question, or what is missing; None when the question is not about these amounts."""
    asks = [k for k, pattern in (('salary', r'봉급|월급|기본급|본봉'), ('holiday', r'명절\s*휴가비'), ('longevity', r'정근\s*수당'),
                                 ('family', r'가족\s*수당'), ('subsidy', r'직급\s*보조비'),
                                 ('overtime', r'시간외\s*(?:근무)?\s*수당|초과\s*근무|야근\s*수당|시간외\s*근무'),
                                 ('night', r'야간\s*근무\s*수당'), ('holiday_work', r'휴일\s*근무\s*수당'))
            if re.search(pattern, question)]
    if not asks or not re.search(r'얼마|계산|금액|몇\s*원|나와|받아|받나|단가|\d+\s*호봉|급\s*\d|\d+\s*시간', question):
        return None
    manifest, tables = load()
    rank, step, years = _rank(question), re.search(r'(\d{1,2})\s*호봉', question), _years(question)
    # Police and fire ranks are national; general grades follow the question or the user's workplace.
    scope = 'local' if re.search(r'지방', question + ' ' + context) and (not rank or rank[0] == 'salary-general') else 'national'
    needs, lines, sources, notes = [], [], [], []
    monthly = None
    if rank and step and {'salary', 'holiday', 'longevity'} & set(asks):
        table = tables[rank[0]]
        row = table['rows'].get(str(int(step[1])))
        monthly = row[rank[1]] if row else None
        if monthly is None:
            notes.append(f'{rank[2]}에는 {int(step[1])}호봉이 없습니다. 봉급표의 호봉 범위를 확인하세요.')
        else:
            lines.append(dict(label=f'{rank[2]} {int(step[1])}호봉 월봉급액', amount=monthly, formula='봉급표 금액'))
            sources.append(_source(manifest[rank[0]]))
    elif {'salary', 'holiday', 'longevity'} & set(asks):
        needs += [x for x, ok in (('직급(예: 7급, 소방교)', rank), ('호봉(예: 5호봉)', step)) if not ok]
    if 'subsidy' in asks:
        if not rank:
            if '직급(예: 7급, 소방교)' not in needs:
                needs.append('직급(예: 7급, 소방교)')
        else:
            key = 'subsidy-local' if scope == 'local' else 'subsidy-national'
            column = 'police_fire' if rank[0] == 'salary-police-fire' else 'general'
            lines.append(dict(label=f'직급보조비(매월, {rank[2]})', amount=tables[key][column][rank[1]], formula='직급보조비 지급구분표 금액'))
            if scope == 'local' and rank[2] == '4급':
                notes.append(f"4급 부단체장은 월 {_won(tables[key]['deputy_4'][0])}입니다.")
            notes.append(f"{ARTICLES['subsidy'][scope]}: 직급별 월 지급액. 파견 근무는 가산, 전용승용차량을 제공받으면 감액하는 기준이 별표 비고에 있습니다.")
            sources.append(_source(manifest[key]))
    if 'family' in asks:
        key = 'family-local' if scope == 'local' else 'family-national'
        rule = tables[key]
        spouse, children, other = _family(question)
        if other is None:
            needs.append('자녀 외 부양가족 수(예: 부모님 2명)')
        elif not (spouse or children or other):
            needs.append('부양가족(예: 배우자, 자녀 2명)')
        else:
            if spouse:
                lines.append(dict(label='가족수당 배우자(매월)', amount=rule['spouse'], formula='배우자 지급액'))
            for i in range(children):
                amount = rule['children'][min(i, 2)]
                lines.append(dict(label=f'가족수당 {ORDINAL[i] if i < len(ORDINAL) else f"{i + 1}번째"} 자녀(매월)', amount=amount, formula=['첫째', '둘째', '셋째 이후'][min(i, 2)] + ' 자녀 지급액'))
            if other:
                lines.append(dict(label=f'가족수당 그 밖의 부양가족 {other}명(매월)', amount=rule['other'] * other, formula=f"{_won(rule['other'])} × {other}명"))
            if spouse + other + children > 4 and spouse + other:
                notes.append('부양가족은 4명 이내로 인정하고 자녀만 4명을 넘어도 지급합니다. 배우자·그 밖의 부양가족 중 인정 인원은 급여 담당 부서에 확인하세요.')
            notes.append(f"{ARTICLES['family'][scope]}: 주민등록상 세대를 같이하고 생계를 같이하는 부양가족 기준. 부부가 모두 공무원이면 한 명에게만 지급합니다.")
            sources.append(_source(manifest[key]))
    if 'holiday' in asks and monthly:
        lines.append(dict(label='명절휴가비(설·추석 각각)', amount=monthly * 60 // 100, formula=f'{_won(monthly)} × 60%'))
        notes.append(f"{ARTICLES['holiday'][scope]}: 설날·추석날 현재 월봉급액의 60%를 각각 지급. 감봉 중이면 감액 전 봉급 기준.")
    if 'longevity' in asks:
        key = 'longevity-local' if scope == 'local' else 'longevity-national'
        rule = tables[key]
        if years is None:
            needs.append('근무연수(예: 재직 7년)')
        else:
            pct = next((p for y, p in rule['under'] if years < y), rule['at_least'][1])
            bonus = next(b for y, b in rule['bonus'] if years >= y) + next((e for y, e in rule['extra'] if years >= y), 0)
            if monthly:
                lines.append(dict(label=f'정근수당(1월·7월 각각, 근무연수 {years}년)', amount=monthly * pct // 100, formula=f'{_won(monthly)} × {pct}%'))
            else:
                notes.append(f'근무연수 {years}년의 정근수당은 월봉급액의 {pct}%입니다. 직급과 호봉을 알려주시면 금액을 계산합니다.')
            lines.append(dict(label='정근수당 가산금(매월)', amount=bonus, formula=f'근무연수 {years}년 구간'))
            notes.append(f"{ARTICLES['longevity'][scope]}: 1월·7월 보수지급일에 지급. 지급대상기간 중 징계처분·휴직·신규임용은 감액·제외 기준이 따로 있습니다.")
            sources.append(_source(manifest[key]))
    if {'overtime', 'night', 'holiday_work'} & set(asks):
        key = 'overtime-local' if scope == 'local' else 'overtime-national'
        police = bool(rank) and rank[0] == 'salary-police-fire'
        rates = rank and tables[key].get('police_fire' if police else 'general', {}).get(str(rank[1] if police else rank[1] + 1))
        if not rank:
            if '직급(예: 7급, 소방교)' not in needs:
                needs.append('직급(예: 7급, 소방교)')
        elif not rates:
            notes.append(f'{rank[2]}은 초과근무수당 지급단가표(일반직 5급~9급, 경정·소방령~순경·소방사)에 없습니다. 해당 직급의 기준은 급여 담당 부서에 확인하세요.')
        else:
            hours = re.search(r'(\d{1,3})\s*시간', question)
            days = re.search(r'(\d{1,2})\s*일', question)
            for kind, index, label, unit, count in (('overtime', 0, '시간외근무수당', '시간당', hours), ('night', 1, '야간근무수당', '시간당', hours),
                                                    ('holiday_work', 2, '휴일근무수당', '1일', days)):
                if kind not in asks or kind == 'night' and 'overtime' in asks:
                    continue
                lines.append(dict(label=f'{label} {unit} 단가({rank[2]})', amount=rates[index], formula='초과근무수당 지급단가표 금액'))
                if count and int(count[1]):
                    n = int(count[1]); suffix = '시간' if unit == '시간당' else '일'
                    lines.append(dict(label=f'{label} {n}{suffix}', amount=rates[index] * n, formula=f'{_won(rates[index])} × {n}{suffix}'))
            notes.append(f"{manifest[key]['law']}: 시간외근무수당은 매 시간 봉급기준액(기준호봉 봉급액×55%)×1/209×150%. "
                         '일반대상자는 월 출근 15일 이상이면 월 10시간분을 정액으로 받습니다. 월 인정 한도와 현업 여부는 기관 기준을 확인하세요.')
            sources.append(_source(manifest[key]))
    if not lines and not needs and not notes:
        return None
    return dict(title='봉급표 기준 계산', lines=lines, needs=needs, notes=notes, sources=sources,
                scope='2026년 봉급표와 수당 규정(별표·조문)의 금액입니다. 세금·공제 전 금액이며, 실제 지급액은 기관 급여 담당 부서의 명세서로 확인하세요.')
