"""Ask pay calculation questions on two sites and compare the amounts and sources.

usage: python -X utf8 tools/check_pay_parity.py <local-url> <public-url> <out.json>
Uses /api/ask without AI; the calculation never uses a model.
"""
import json, sys
import httpx

QUESTIONS = [
    '9급 1호봉 봉급 얼마야?', '소방교 5호봉 명절휴가비 얼마 나와?', '7급 10호봉 재직 7년 정근수당 계산해줘',
    '5급 20호봉 재직 22년 정근수당 얼마', '소방정 3호봉 월급 얼마?', '경감 2호봉 봉급 얼마', '1급 30호봉 봉급 얼마',
    '명절휴가비 얼마나 나와?', '정근수당 계산해줘 재직 7년', '연가는 며칠이야?',
    '배우자랑 자녀 둘 있으면 가족수당 얼마야?', '부모님 모시면 가족수당 얼마', '7급 직급보조비 얼마야?',
    '소방위 직급보조비 얼마', '9급 3호봉 봉급이랑 직급보조비 얼마',
    '7급 시간외근무수당 20시간 얼마?', '소방교 초과근무 15시간 수당 얼마', '9급 휴일근무수당 2일 얼마', '4급 시간외근무수당 얼마',
]


def ask(site, question):
    with httpx.Client(base_url=site, headers={'Origin': site, 'User-Agent': 'Mozilla/5.0 gongmudam-release-check'}, timeout=180) as c:
        r = c.post('/api/ask', json=dict(query=question, use_ai=False, guidance=True, today='2026-11-03'))
        r.raise_for_status()
        calc = r.json().get('pay_calculation')
    return calc and dict(lines=[(l['label'], l['amount']) for l in calc['lines']], needs=calc['needs'],
                         notes=calc['notes'], sources=[s['sha256'] for s in calc['sources']])


local, public, out = sys.argv[1].rstrip('/'), sys.argv[2].rstrip('/'), sys.argv[3]
rows = []
for q in QUESTIONS:
    a, b = ask(local, q), ask(public, q)
    rows.append(dict(question=q, same=a == b, local=a, public=b))
    print(q, '| 같음' if a == b else '| 다름', '|', (a or {}).get('lines'))
json.dump(rows, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(json.dumps(dict(same=sum(r['same'] for r in rows), of=len(rows)), ensure_ascii=False))
