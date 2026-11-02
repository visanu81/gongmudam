"""Synthetic application-form HWPX: ask the same questions locally (temp DB, Solar) and on the shared site."""
import json, sys, tempfile, time, zipfile
from pathlib import Path
from unittest.mock import patch
import httpx

SITE = 'https://gongmudam.visanu81.workers.dev'
QUESTIONS = [('이 사람의 소속은?', '부서: 민원과'), ('참가자 이름과 직급은?', '직급: 주무관'),
             ('담당부서는 어디야?', '담당부서명: 총무과 기획팀'), ('기관명은?', '기관명: 가람시청')]
ns = 'http://www.hancom.co.kr/hwpml/2011/paragraph'
def para(t): return f'<hp:p><hp:run><hp:t>{t}</hp:t></hp:run></hp:p>'
def cell(t, col, row, cs=1, rs=1):
    return (f'<hp:tc><hp:subList>{para(t)}</hp:subList><hp:cellAddr colAddr="{col}" rowAddr="{row}"/>'
            f'<hp:cellSpan colSpan="{cs}" rowSpan="{rs}"/></hp:tc>')
rows = [[cell('참가 구분', 0, 0, 2), cell('■ 개인 □ 팀 (팀명: )', 2, 0, 6)],
        [cell('기관 정보', 0, 1, 1, 2), cell('기관명', 1, 1), cell('가람시청', 2, 1, 6)],
        [cell('담당부서명', 1, 2), cell('총무과 기획팀', 2, 2, 6)],
        [cell('참가자 정보', 0, 3, 8)],
        [cell(v, c, 4) for c, v in enumerate(['구분', '성명', '부서', '직급', '직위', '연락처', '이메일', '역할'])],
        [cell(v, c, 5) for c, v in enumerate(['개인', '홍길동', '민원과', '주무관', '', '010-0000-0000', 'a@example.test', '개발'])],
        [cell('과제명', 0, 6, 2), cell('합성 도우미', 2, 6, 6)]]
trs = ''.join('<hp:tr>' + ''.join(r) + '</hp:tr>' for r in rows)
xml = (f'<hs:sec xmlns:hp="{ns}" xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section">{para("[합성] 참가신청서")}'
       f'<hp:p><hp:run><hp:tbl rowCnt="7" colCnt="8">{trs}</hp:tbl></hp:run></hp:p></hs:sec>')
docs = Path(tempfile.mkdtemp()) / 'form'; docs.mkdir()
path = docs / '참가신청서_합성.hwpx'
with zipfile.ZipFile(path, 'w') as z: z.writestr('Contents/section0.xml', xml)

sys.path.insert(0, '.')
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import config, folders, folder_projects as projects, project_text

def ask_all(client, pid, poll):
    out = {}
    for q, fact in QUESTIONS:
        client.post(f'/api/folder-projects/{pid}/messages', json={'content': q}).raise_for_status()
        while (m := client.get(f'/api/folder-projects/{pid}').json()['messages'][-1])['status'] != 'completed': time.sleep(poll)
        texts = [e['text'] for e in m.get('evidence') or []]
        out[q] = dict(found=any(fact in t for t in texts), mode=m['mode'], evidence=texts)
    return out

print('units', [u['text'] for u in project_text.extract(path)['units']])
prof = dict(config.load()['llm']['profiles']['upstage'], _name='upstage')
root = Path(tempfile.mkdtemp())
with patch.object(folders, 'DB_PATH', root / 'f.db'), patch.object(config, 'active_profile', return_value=prof), \
     patch.object(projects, 'parse_file', side_effect=lambda p, t: project_text.extract(p)):
    folders.initialize(); projects.initialize(); app = FastAPI(); app.include_router(projects.router)
    c = TestClient(app, client=('127.0.0.1', 1), base_url='http://127.0.0.1:9988')
    w = projects.Worker().start(); pid = c.post('/api/folder-projects', json={'name': '서식 확인'}).json()['id']
    c.post(f'/api/folder-projects/{pid}/sources', json={'kind': 'folder', 'paths': [str(docs)]}, headers={'origin': 'http://127.0.0.1:9988'})
    while not ((v := c.get(f'/api/folder-projects/{pid}').json())['files'] and all(f['status'] == 'ready' for f in v['files'])): time.sleep(.3)
    local = ask_all(c, pid, .3); w.stop()

pc = httpx.Client(base_url=SITE, headers={'Origin': SITE, 'User-Agent': 'Mozilla/5.0 gongmudam-release-check'}, timeout=180)
pid = pc.post('/api/folder-projects', json={'name': '서식 확인 합성'}).raise_for_status().json()['id']
lib = pc.post('/api/folders/uploads', data={'name': '서식 확인 합성', 'paths': json.dumps([path.name]), 'situation': '', 'public_consent': 'true'},
              files=[('files', (path.name, path.read_bytes()))]).raise_for_status().json()
pc.post(f'/api/folder-projects/{pid}/libraries', json={'library_id': lib['id']}).raise_for_status()
while not ((v := pc.get(f'/api/folder-projects/{pid}').json())['files'] and all(f['status'] == 'ready' for f in v['files'])): time.sleep(2)
public = ask_all(pc, pid, 2)
rows = [dict(question=q, local=local[q], public=public[q], same_evidence=local[q]['evidence'] == public[q]['evidence']) for q, _ in QUESTIONS]
Path(sys.argv[1]).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
for r in rows: print(r['question'], '| 로컬', r['local']['found'], r['local']['mode'], '| 공유', r['public']['found'], r['public']['mode'], '| 같은 근거', r['same_evidence'])
