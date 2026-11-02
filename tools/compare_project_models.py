"""Compare models where 업무자료 정리 uses AI: choosing the evidence refs for a project question.

usage (from service/): python -X utf8 ../tools/compare_project_models.py <docs-dir> <out.json> <profile> [base_url] [model]
A temporary project reads the synthetic documents; nothing touches the personal database.
EXTRA_BODY (JSON) is merged into the profile, e.g. {"reasoning_effort":"none"}.
"""
import json, os, sys, tempfile, time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, '.')
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import config, folders, folder_projects as projects, local_ai, project_text

# question, facts that the chosen evidence must contain
CASES = [
    ('교육 일정이 언제야?', ['11. 13.']),
    ('미회신 부서와 재요청 기한은?', ['회계과', '11. 7.']),
    ('교재비 총액은 얼마야?', ['345,000']),
    ('정보화담당관 참석 인원은?', ['정보화담당관', '7']),
    ('교육 소요 예산 내역을 알려줘', ['1,200,000', '345,000']),
    ('중복 신청은 몇 건이야?', ['중복 신청 2건']),
    ('물품 납품 후 검사는 며칠 안에 해야 해?', ['14일 이내에 검사']),
    ('물품 대금은 언제까지 지급해?', ['5일 이내에 대금']),
    ('물품 구매 요구서는 언제까지 내야 해?', ['14일 전까지']),
    ('견적은 몇 명에게 받아야 해?', ['2인 이상']),
    ('여비 정산서에 적어야 하는 항목은?', ['숙박비', '출장 기간']),
    ('교육 취합 결과와 물품 구매 지침을 비교해줘', ['교육', '물품']),
    ('체육대회 일정은 언제야?', []),
]

docs, out, name = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
profile = dict(config.load()['llm']['profiles'][name]); profile['_name'] = name
if len(sys.argv) > 4: profile['base_url'] = sys.argv[4]
if len(sys.argv) > 5: profile['model'] = sys.argv[5]
if os.environ.get('EXTRA_BODY'): profile['extra_body'] = json.loads(os.environ['EXTRA_BODY'])

root = Path(tempfile.mkdtemp())
with patch.object(folders, 'DB_PATH', root / 'folders.db'), \
     patch.object(config, 'active_profile', return_value=profile), \
     patch.object(local_ai, 'local_profile', return_value=dict(profile)), \
     patch.object(projects, 'parse_file', side_effect=lambda path, tick: project_text.extract(path)):
    folders.initialize(); projects.initialize()
    app = FastAPI(); app.include_router(projects.router)
    client = TestClient(app, client=('127.0.0.1', 1234), base_url='http://127.0.0.1:9988')
    headers = {'origin': 'http://127.0.0.1:9988'}
    worker = projects.Worker().start()
    pid = client.post('/api/folder-projects', json={'name': '합성 비교'}).json()['id']
    client.post(f'/api/folder-projects/{pid}/sources', json={'kind': 'folder', 'paths': [str(docs)]}, headers=headers)
    end = time.monotonic() + 900
    while time.monotonic() < end:
        v = client.get(f'/api/folder-projects/{pid}').json()
        if v['files'] and all(f['status'] in ('ready', 'partial', 'failed', 'unsupported') for f in v['files']) and not any(j['status'] in ('queued', 'running') for j in v.get('jobs', [])):
            break
        time.sleep(1)
    print('files', [(f['name'], f['status']) for f in v['files']], flush=True)
    rows = []
    for question, facts in CASES:
        started = time.perf_counter()
        client.post(f'/api/folder-projects/{pid}/messages', json={'content': question})
        while True:
            v = client.get(f'/api/folder-projects/{pid}').json(); m = v['messages'][-1]
            if m['status'] in ('completed', 'failed'): break
            time.sleep(.2)
        texts = ' '.join(e['text'] for e in m.get('evidence') or [])
        hit = [f for f in facts if f in texts]
        rows.append(dict(question=question, facts=facts, found=hit, all_found=len(hit) == len(facts), mode=m.get('mode'),
                         refs=len(m.get('evidence') or []), files=sorted({e['name'] for e in m.get('evidence') or []}),
                         seconds=round(time.perf_counter() - started, 2), notice=m.get('notice', '')[:160],
                         content=m.get('content', '')[:600]))
        print(question, '|', m.get('mode'), '|', len(hit), '/', len(facts), '| refs', rows[-1]['refs'], '|', rows[-1]['seconds'], 's', flush=True)
    worker.stop(); client.close()
Path(out).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
answerable = [r for r in rows if r['facts']]
print(json.dumps(dict(model=profile.get('model'), questions=len(rows), all_facts=sum(r['all_found'] for r in answerable), of=len(answerable),
                      ai_used=sum(r['mode'] in ('upstage_ai', 'local_ai') for r in rows), fallback=sum(r['mode'] == 'fallback' for r in rows),
                      avg_refs=round(sum(r['refs'] for r in rows) / len(rows), 1), avg_seconds=round(sum(r['seconds'] for r in rows) / len(rows), 2)), ensure_ascii=False))
