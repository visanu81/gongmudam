"""Create a synthetic notebook in a fresh private submission; never use a live work install."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import urlsplit
import httpx

ROOT = Path(__file__).resolve().parents[1]


def run(base):
    url = urlsplit(base)
    if url.scheme != 'http' or url.hostname not in {'localhost', '127.0.0.1'} or url.path not in {'', '/'} or url.query or url.fragment or url.username:
        raise ValueError('Use a private localhost submission test server')
    if not (ROOT/'data/submission-installation.json').is_file():
        raise ValueError('Install the submission in a fresh test folder first')
    checks, answers = {}, []
    sample = ROOT/'sample_data/notebook-v80'
    originals = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in sample.rglob('*') if p.is_file()}
    with httpx.Client(base_url=base.rstrip('/'), timeout=45, trust_env=False) as c:
        def request(method, path, **kwargs):
            r = c.request(method, path, **kwargs)
            r.raise_for_status()
            return r.json()
        def detail():
            return request('GET', endpoint)
        def wait(predicate):
            end = time.monotonic()+90
            while time.monotonic() < end:
                v = detail()
                if predicate(v):
                    return v
                time.sleep(.25)
            raise AssertionError('Timed out waiting for reading/answer')
        status = request('GET', '/api/gongmudam/status')
        assert not status['public_demo']
        assert request('GET', '/api/settings')['llm']['active'] == 'offline', 'Keep this test AI-free'
        checks['private_offline'] = True
        bundle = json.loads((ROOT/'submission-data/knowledge.json').read_text(encoding='utf-8'))
        sources = request('GET', '/api/knowledge/sources')
        assert {s['id'] for s in sources} == {s['id'] for s in bundle['sources']}
        assert all(s['enabled'] and s['current'] for s in sources)
        checks['registered_sources'] = len(sources)
        pid = request('POST', '/api/folder-projects', json={'name':'[합성 검증] v80 교육 노트'})['id']
        endpoint = '/api/folder-projects/'+pid
        for kind, path in [('folder', sample/'교육 자료'), ('file', sample/'취합 확인사항.md')]:
            request('POST', endpoint+'/sources', json={'kind':kind, 'paths':[str(path)]}, headers={'Origin':base.rstrip('/')})
        value = wait(lambda v: len(v['files']) == 3 and v['jobs'] and all(j['status']=='completed' for j in v['jobs']))
        checks['folder_and_file'] = len(value['files']) == 3
        for question in ['미회신 부서는 어디인가요?', '핵심 내용을 요약해줘', '일정과 할 일을 알려줘', '자료를 비교해줘', '보고서 초안을 작성해줘', '항공권 취소 수수료는 얼마인가요?']:
            before = {m['id'] for m in detail()['messages']}
            request('POST', endpoint+'/messages', json={'content':question, 'draft':'초안' in question})
            v = wait(lambda v: any(m['id'] not in before and m.get('role')=='assistant' and m['status']=='completed' for m in v['messages']))
            answer = next(m for m in reversed(v['messages']) if m['id'] not in before and m.get('role')=='assistant')
            assert answer['mode']=='offline'
            if '취소' in question:
                assert not answer['evidence'], answer
            else:
                assert answer['evidence'], answer
            if '미회신' in question:
                assert '회계과' in answer['content']
                assert any(e['loc']=='3행' and '회계과' in e['text'] for e in answer['evidence'])
            for e in answer['evidence']:
                path = endpoint+f"/files/{e['file_id']}"
                unit = request('GET', path+f"/units/{e['unit']}", params={'sha256':e['sha256']})
                assert unit['text']==e['text']
                original = c.get(path+'/original', params={'sha256':e['sha256']})
                original.raise_for_status()
                assert hashlib.sha256(original.content).hexdigest()==e['sha256']
            if '초안' in question:
                request('PATCH', endpoint+'/messages/'+answer['id'], json={'content':answer['content']+'\n담당자 검토: 합성 예제 확인'})
                checks['draft_edit_saved'] = '담당자 검토' in detail()['messages'][-1]['content']
            answers.append({'question':question, 'answer':answer})
        checks['original_files_unchanged'] = all(hashlib.sha256(p.read_bytes()).hexdigest()==sha for p,sha in originals.items())
        checks['reopen_preserved'] = len(detail()['files'])==3 and len(detail()['messages'])==12
        assert all(checks.values()), checks
        return {'passed':True, 'checked_at':datetime.now(timezone.utc).isoformat(), 'version':status['service_version'],
                'checks':checks, 'project_id':pid, 'answers':answers, 'snapshot':detail(),
                'scope':'Same PC, fresh extracted installation; synthetic data; no actual AI model calls'}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base', required=True)
    p.add_argument('--output', type=Path, required=True)
    a=p.parse_args()
    result=run(a.base)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('answers','snapshot')},ensure_ascii=False))
