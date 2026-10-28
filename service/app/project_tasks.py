"""Bounded, extractive document tasks. Every reported fact retains its source unit."""
from collections import defaultdict
import re

LABELS = {'title': '교육·업무명', 'when': '일정', 'where': '장소', 'deadline': '마감·기한',
          'who': '대상', 'owner': '담당자', 'amount': '금액·예산', 'status': '진행 상황',
          'action': '다음 할 일', 'other': '원문 발췌'}
ORDER = ['title', 'deadline', 'when', 'where', 'who', 'status', 'action', 'owner', 'amount', 'other']
PATTERNS = [
    ('action', r'^(?:다음\s*할\s*일|할\s*일|다음\s*조치|조치|요청사항)\s*[:：]|(?:제출|검토|확정|확인|회신|취합|수집|전달|요청|배포)\s*(?:하|해)|보내야'),
    ('deadline', r'마감|기한|제출.*까지|회신.*까지'),
    ('title', r'^(?:교육명|업무명|행사명|제목)\s*[:：]'),
    ('where', r'^(?:장소|교육장|개최장소|회의장소)\s*[:：]'),
    ('who', r'^(?:대상|대상\s*부서|참석\s*대상)\s*[:：]'),
    ('owner', r'^(?:담당|담당자|담당\s*부서)\s*[:：]'),
    ('amount', r'금액|예산|소요액'),
    ('status', r'미회신|회신\s*완료|\d+명.*회신|진행\s*상태|회신\s*대기'),
    ('when', r'교육일|일시|개최일|행사일|날짜|20\d\d[-./]\d|\d+월\s*\d+일|\d+시|오늘|내일|모레|다음\s*주'),
]


def facts(text):
    for raw in text.splitlines():
        line = raw.strip()
        if not line or re.fullmatch(r'\[.*자료.*\]', line):
            continue
        match_line = re.sub(r'^(?:[-•●*]|\d+[.)])\s*', '', line)
        field = next((key for key, pattern in PATTERNS if re.search(pattern, match_line)), 'other')
        # Labels identifying a document are not a useful replacement for its facts.
        if field == 'other' and re.match(r'^(?:문서|비고)\s*[:：]', line):
            continue
        yield field, line


def retrieve(c, pid, files, plan):
    sql = 'SELECT u.file_id,u.unit,u.loc,u.text FROM project_units u JOIN project_files f ON f.id=u.file_id WHERE f.project_id=?'
    topics = plan['topics']
    if topics:
        hits = {fid: {word for word in topics if word in f['name'].lower()} for fid, f in files.items()}
        for fid, _, _, text in c.execute(sql, (pid,)):
            if fid in hits:
                hits[fid].update(word for word in topics if word in text.lower())
        files = {fid: f for fid, f in files.items() if all(word in hits[fid] for word in topics)}
    files = dict(sorted(files.items(), key=lambda item: (item[1]['name'].casefold(), item[0]))[:24])
    # At most two units per field per file. Even a long PDF is streamed, never
    # concatenated. The final source budget stays at 24 units / 24,000 characters.
    pools = {}
    for fid, unit, loc, text in c.execute(sql, (pid,)):
        if fid not in files:
            continue
        pool = pools.setdefault(fid, {})
        ev = dict(file_id=fid, unit=unit, loc=loc, text=text, name=files[fid]['name'],
                  sha256=files[fid]['sha256'], stale=False)
        for field in dict.fromkeys(key for key, _ in facts(text)):
            values = pool.setdefault(field, [])
            if len(values) < 2 and not any(item['unit'] == unit for item in values):
                values.append(ev)
    fields = ORDER
    if plan['mode'] == 'schedule':
        fields = ['deadline', 'when', 'action', 'owner']
    elif plan['mode'] == 'compare' and plan['fields']:
        fields = plan['fields']
    ordered = {}
    for fid in sorted(pools, key=lambda key: (files[key]['name'].casefold(), key)):
        items, seen = [], set()
        for index in range(2):
            for field in fields:
                values = pools[fid].get(field, [])
                if index < len(values) and values[index]['unit'] not in seen:
                    items.append(values[index]); seen.add(values[index]['unit'])
        if not items and plan['mode'] == 'compare':
            # Keep the compared file visible even if the requested field is
            # absent. Its title/other source unit supplies file context only.
            fallback = next((pools[fid][key][0] for key in ORDER if pools[fid].get(key)), None)
            if fallback:
                items.append(fallback)
        if items:
            ordered[fid] = items
    result, chars = [], 0
    for index in range(max((len(items) for items in ordered.values()), default=0)):
        for items in ordered.values():
            if index >= len(items):
                continue
            ev = items[index]
            if len(result) >= 24 or chars + len(ev['text']) > 24000:
                continue
            chars += len(ev['text']); result.append(ev | {'ref': len(result) + 1})
    return result


def _items(evidence):
    result = []
    for e in evidence:
        for field, line in facts(e['text']):
            result.append(dict(field=field, line=line, value=line if field == 'other' else re.split(r'[:：]', line, maxsplit=1)[-1].strip(),
                               ref=e['ref'], file_id=e['file_id'], name=e['name']))
    return result


def _lines(items, fields):
    grouped = {}
    for item in items:
        if item['field'] not in fields:
            continue
        key = item['field'], re.sub(r'\s+', '', item['line'])
        entry = grouped.setdefault(key, [item['line'], []])
        if item['ref'] not in entry[1]:
            entry[1].append(item['ref'])
    return ['- ' + line + ' ' + ' '.join(f'[{ref}]' for ref in refs) for line, refs in grouped.values()]


def _different(items):
    for field in ('title', 'when', 'where', 'deadline', 'who', 'amount'):
        by_file = defaultdict(set)
        for item in items:
            if item['field'] == field:
                by_file[item['file_id']].add(re.sub(r'\s+', '', item['value']))
        values = list(by_file.values())
        if len(values) > 1 and any(value != values[0] for value in values[1:]):
            return True
    return False


def format_answer(plan, evidence, name):
    """Template wording is visibly distinct from verbatim, numbered source facts."""
    items = _items(evidence)
    if plan['mode'] == 'compare':
        files = dict.fromkeys((e['file_id'], e['name']) for e in evidence)
        if len(files) < 2:
            return '비교할 수 있는 자료가 두 개 이상 필요합니다. 자료를 추가하거나 비교할 파일을 선택해 주세요.'
        lines = ['자료 비교 · 원문에 적힌 값 기준', '차이는 문서별 값의 차이입니다. 어느 문서를 적용할지는 담당자가 확인하세요.']
        fields = plan['fields'] or [key for key in ORDER if any(i['field'] == key for i in items)]
        for field in fields:
            groups = [[i for i in items if i['file_id'] == fid and i['field'] == field] for fid, _ in files]
            values = [{re.sub(r'\s+', '', i['value']) for i in group} for group in groups]
            verdict = '같음' if all(values) and all(v == values[0] for v in values) else '차이' if all(values) else '확인 필요'
            lines.append(f'{LABELS[field]} · {verdict}')
            for (fid, filename), group in zip(files, groups):
                if group:
                    unique = {(i['line'], i['ref']) for i in group}
                    lines.extend(f'- {filename}: {line} [{ref}]' for line, ref in sorted(unique))
                else:
                    refs = ' '.join(f"[{e['ref']}]" for e in evidence if e['file_id'] == fid)
                    lines.append(f'- {filename}: 이번 발췌에서 확인되지 않음 {refs}')
        return '\n'.join(lines)
    if plan['mode'] == 'draft':
        sections = [('1. 업무 개요', ['title', 'when', 'deadline', 'where', 'who', 'owner', 'amount']),
                    ('2. 확인된 진행 상황', ['status']), ('3. 다음 조치', ['action'])]
        if items and all(item['field'] == 'other' for item in items):
            sections[1] = ('2. 확인된 원문 내용', ['other'])
        lines = [name + ' · 보고서 초안', '원문 발췌형 초안 · 담당자 검토 전']
        for heading, fields in sections:
            lines.append(heading)
            lines.extend(_lines(items, fields) or ['[작성 필요: 자료에서 해당 내용을 확인하지 못했습니다.]'])
        lines += ['4. 담당자 확인사항', '목적: [작성 필요]', '최종 적용 일정·문서: [작성 필요]',
                  '내부 승인·실제 발송 여부: [작성 필요]']
    elif plan['mode'] == 'schedule':
        lines = ['일정과 할 일 · 원문 발췌', '날짜나 완료 여부를 추정하지 않았습니다.']
        for heading, fields in [('일정·기한', ['when', 'deadline']), ('할 일', ['action', 'owner'])]:
            lines.append(heading)
            lines.extend(_lines(items, fields) or ['자료에서 명시된 내용을 찾지 못했습니다.'])
    else:
        lines = ['핵심 요약 · 원문 발췌']
        for heading, fields in [('교육·업무', ['title']), ('일정·마감·장소', ['when', 'deadline', 'where']),
                                ('대상·진행 상황', ['who', 'status', 'owner', 'amount']), ('다음 할 일', ['action'])]:
            values = _lines(items, fields)
            if values:
                lines.append(heading); lines.extend(values)
        if len(lines) == 1:
            lines.extend(_lines(items, ['other']))
    if _different(items):
        lines.append('확인 필요: 문서별로 일정·장소 등에 다른 값이 있습니다. 적용할 문서를 확인하세요.')
    return '\n'.join(lines)
