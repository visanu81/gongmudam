"""봉급·명절휴가비·정근수당 amounts from the official 2026 annexes, without AI.

The answer search finds the articles; the amounts are in annex tables
(공무원보수규정 별표 3·10, 수당 규정 별표 2) collected by tools/collect_pay_tables.py.
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
}


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


def _won(n):
    return f'{n:,}원'


def calculate(question, context=''):
    """Amounts for a pay question, or what is missing; None when the question is not about these amounts."""
    asks = [k for k, pattern in (('salary', r'봉급|월급|기본급|본봉'), ('holiday', r'명절\s*휴가비'), ('longevity', r'정근\s*수당'))
            if re.search(pattern, question)]
    if not asks or not re.search(r'얼마|계산|금액|몇\s*원|나와|받아|받나|\d+\s*호봉|급\s*\d', question):
        return None
    manifest, tables = load()
    rank, step, years = _rank(question), re.search(r'(\d{1,2})\s*호봉', question), _years(question)
    # Police and fire ranks are national; general grades follow the question or the user's workplace.
    scope = 'local' if re.search(r'지방', question + ' ' + context) and (not rank or rank[0] == 'salary-general') else 'national'
    needs, lines, sources, notes = [], [], [], []
    monthly = None
    if rank and step:
        table = tables[rank[0]]
        row = table['rows'].get(str(int(step[1])))
        monthly = row[rank[1]] if row else None
        if monthly is None:
            notes.append(f'{rank[2]}에는 {int(step[1])}호봉이 없습니다. 봉급표의 호봉 범위를 확인하세요.')
        else:
            lines.append(dict(label=f'{rank[2]} {int(step[1])}호봉 월봉급액', amount=monthly, formula='봉급표 금액'))
            sources.append(_source(manifest[rank[0]]))
    else:
        needs += [x for x, ok in (('직급(예: 7급, 소방교)', rank), ('호봉(예: 5호봉)', step)) if not ok]
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
    if not lines and not needs and not notes:
        return None
    return dict(title='봉급표 기준 계산', lines=lines, needs=needs, notes=notes, sources=sources,
                scope='2026년 봉급표·수당 규정 별표의 금액입니다. 세금·공제 전 금액이며, 실제 지급액은 기관 급여 담당 부서의 명세서로 확인하세요.')
