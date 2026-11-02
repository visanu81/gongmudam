"""Compare models on the step where 공무담 uses AI in answers: picking the one source passage.

usage (from service/): python -X utf8 ../tools/compare_quote_models.py <profile-name> <out.json> [base_url] [model]
Runs from service/. Retrieval is AI-free; only the selection call differs per model.
"""
import json, sys, time
from datetime import date
sys.path.insert(0, '.')
from app import config, knowledge, llm

name, out = sys.argv[1], sys.argv[2]
profile = dict(config.load()['llm']['profiles'][name])
if len(sys.argv) > 3: profile['base_url'] = sys.argv[3]
if len(sys.argv) > 4: profile['model'] = sys.argv[4]
profile['timeout'] = 120
import os
if os.environ.get('EXTRA_BODY'): profile['extra_body'] = json.loads(os.environ['EXTRA_BODY'])
provider = llm.get_provider(profile)
cases = json.load(open('reference_data/service_rules_checks.json', encoding='utf-8'))
cases = cases['cases'] if isinstance(cases, dict) else cases
rows = []
for case in cases:
    q = case['question']
    found = knowledge.retrieve(q, None, date(2026, 11, 2))
    row = dict(id=case['id'], question=q, expected=case.get('article'))
    if not found['hits']:
        row.update(status='no_hits'); rows.append(row); continue
    choices = knowledge.quote_choices(found['hits'], q)
    row['choices'] = len(choices)
    started = time.perf_counter()
    try:
        ev = knowledge._model_evidence(q, found['hits'], provider)
        row.update(status='ok' if ev else 'none_selected')
    except llm.LLMError as e:
        ev = []; row.update(status='error', error=str(e))
    row['seconds'] = round(time.perf_counter() - started, 2)
    if ev:
        hit = next(h for h in found['hits'] if h['id'] == ev[0]['id'])
        row['selected_loc'] = hit.get('loc', '')[:120]
        row['selected_title'] = hit.get('title', '')[:80]
        row['quote'] = ev[0]['quote'][:200]
        art = (case.get('article') or '').split('(')[0].split()[-1] if case.get('article') else ''
        row['article_match'] = bool(art) and art in (hit.get('loc', '') + hit.get('text', '')[:40])
    rows.append(row)
    print(case['id'], row['status'], row.get('seconds'), row.get('article_match'), flush=True)
json.dump(rows, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
ok = [r for r in rows if r.get('status') == 'ok']
print(json.dumps(dict(model=profile.get('model'), total=len(rows), selected=len(ok),
                      article_match=sum(1 for r in ok if r.get('article_match')),
                      errors=sum(1 for r in rows if r.get('status') == 'error'),
                      avg_seconds=round(sum(r['seconds'] for r in ok) / max(len(ok), 1), 2)), ensure_ascii=False))
