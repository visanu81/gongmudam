"""Ask the synthetic 업무자료 정리 questions on the shared site and compare with a local run.

usage: python -X utf8 tools/check_project_search_public.py <site-url> <docs-dir> <local-result.json> <out.json>
<local-result.json> comes from tools/compare_project_models.py with the same documents and model.
Only synthetic and public documents are uploaded; the shared demo resets them when it sleeps.
"""
import json, sys, time
from pathlib import Path
import httpx

site, docs, local_path, out = sys.argv[1].rstrip('/'), Path(sys.argv[2]), sys.argv[3], sys.argv[4]
headers = {'Origin': site, 'User-Agent': 'Mozilla/5.0 gongmudam-release-check'}
client = httpx.Client(base_url=site, headers=headers, timeout=180)


def wait(pid, predicate, limit=900):
    end = time.monotonic() + limit
    while time.monotonic() < end:
        value = client.get(f'/api/folder-projects/{pid}').json()
        if predicate(value):
            return value
        time.sleep(2)
    raise TimeoutError(json.dumps(value, ensure_ascii=False)[:500])


pid = client.post('/api/folder-projects', json={'name': '검색 확인 합성 자료'}).raise_for_status().json()['id']
paths = sorted(docs.iterdir())
files = [('files', (p.name, p.read_bytes())) for p in paths]
library = client.post('/api/folders/uploads', data={'name': '검색 확인 합성 자료', 'paths': json.dumps([p.name for p in paths]),
                                                    'situation': '', 'public_consent': 'true'}, files=files).raise_for_status().json()
client.post(f'/api/folder-projects/{pid}/libraries', json={'library_id': library['id']}).raise_for_status()
v = wait(pid, lambda v: v['files'] and all(f['status'] in ('ready', 'partial', 'failed', 'unsupported') for f in v['files'])
         and not any(j['status'] in ('queued', 'running') for j in v.get('jobs', [])))
print('files', [(f['name'], f['status'], f.get('extractor')) for f in v['files']], flush=True)
# The local result carries the same questions and expected facts.
local = {r['question']: r for r in json.load(open(local_path, encoding='utf-8'))}
rows = []
for question, facts in ((r['question'], r['facts']) for r in local.values()):
    client.post(f'/api/folder-projects/{pid}/messages', json={'content': question}).raise_for_status()
    v = wait(pid, lambda v: v['messages'] and v['messages'][-1]['status'] in ('completed', 'failed'), 300)
    m = v['messages'][-1]
    texts = ' '.join(e['text'] for e in m.get('evidence') or [])
    found = [f for f in facts if f in texts]
    mine = local[question]
    rows.append(dict(question=question, facts=facts, public=dict(found=found, mode=m.get('mode'), refs=len(m.get('evidence') or []),
                     files=sorted({e['name'] for e in m.get('evidence') or []})),
                     local=dict(found=mine['found'], mode=mine['mode'], refs=mine['refs'], files=mine['files']),
                     same_facts=found == mine['found']))
    print(question, '| 공유', len(found), '/', len(facts), m.get('mode'), '| 로컬', len(mine['found']), '/', len(facts), mine['mode'], flush=True)
Path(out).write_text(json.dumps(dict(site=site, project=pid, rows=rows), ensure_ascii=False, indent=1), encoding='utf-8')
print(json.dumps(dict(same_facts=sum(r['same_facts'] for r in rows), of=len(rows),
                      public_all_found=sum(len(r['public']['found']) == len(r['facts']) for r in rows if r['facts'])), ensure_ascii=False))
