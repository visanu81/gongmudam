"""Exercise synthetic institution versions only in a separate restored submission."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]

def run(base):
    if not (ROOT/'data/submission-installation.json').is_file():
        raise RuntimeError('Run only in a separate restored submission installation')
    release_version = json.loads((ROOT/'submission-manifest.json').read_text(encoding='utf-8')).get('release_version')
    assert isinstance(release_version, str) and release_version.strip(), 'Submission manifest release_version must be a nonempty string'
    checks = {}
    with httpx.Client(base_url=base, headers={'Origin':base}, timeout=30) as c:
        def req(method, path, expected=200, **kwargs):
            r = c.request(method, path, **kwargs)
            if r.status_code != expected:
                raise AssertionError(f'{method} {path}: {r.status_code} {r.text[:300]}')
            return r.json()
        status = req('GET','/api/gongmudam/status')
        assert not status['public_demo']
        assert status['service_version'] == release_version
        assert not req('GET','/api/institution-rules?include_deleted=true')['items'], 'Use a fresh installation'
        checks['default_offline'] = req('GET','/api/settings')['llm']['active'] == 'offline'
        sources = req('GET','/api/knowledge/sources')
        checks['registered_sources_86_current'] = len(sources)==86 and all(s['current'] and s['enabled'] for s in sources)
        checks['manuals_6_221_pages'] = sum(s.get('reference_kind')=='system_manual' for s in sources)==6 and sum(s.get('page_count',0) for s in sources)==221
        samples=ROOT/'sample_data/institution-rules-v77'
        v1=(samples/'제출기한_v1.txt').read_bytes();v2=(samples/'제출기한_v2.txt').read_bytes()
        fields={'title':'[합성 예제] 교육자료 제출 안내','institution':'합성 제출검증기관','kind':'기관 지침',
                'keywords':json.dumps(['검증자료 제출'],ensure_ascii=False),'effective_date':'2026-01-01',
                'scope_notes':'실제 법령·지침이 아닌 제출 기능 검증용 합성 자료'}
        doc=req('POST','/api/institution-rules/upload',201,data=fields,files={'file':('제출기한_v1.txt',v1,'text/plain')})
        prefix='/api/institution-rules/'+doc['id']
        def ask(institution='합성 제출검증기관'):
            return req('POST','/api/ask',json={'query':institution+' 검증자료 제출 기한은?',
                       'guidance':True,'use_ai':False,'institution_rule_id':doc['id']})
        draft=ask()
        checks['draft_not_in_answer'] = not draft['knowledge']['evidence'] and '3일 전' not in draft['answer']
        def apply(d):
            v=d['versions'][-1]
            comp=req('GET',prefix+'/compare',params={'from_version':d.get('active_version_id') or '', 'to_version':v['id']})
            return req('PATCH',prefix,json={'revision':comp['revision'],'operation':'apply',
                       'version_id':v['id'],'reviewed_sha256':comp['after']['sha256']}),comp
        doc,_=apply(doc);answer1=ask()
        checks['applied_v1_offline'] = '3일 전' in answer1['answer'] and not answer1['guidance']['ai_used'] and answer1['model'] is None
        stale=doc['revision']
        doc=req('POST','/api/institution-rules/upload',201,data=fields|{'rule_id':doc['id'],'revision':str(doc['revision']),'change_note':'기한 3일 전에서 5일 전으로 변경'},files={'file':('제출기한_v2.txt',v2,'text/plain')})
        answer_draft2=ask()
        checks['v2_draft_keeps_v1_answer'] = '3일 전' in answer_draft2['answer'] and '5일 전' not in answer_draft2['answer']
        req('PATCH',prefix,409,json={'operation':'disable','revision':stale})
        checks['stale_revision_409'] = True
        doc,comparison=apply(doc);answer2=ask()
        checks['comparison_before_after'] = '3일 전' in comparison['before']['text'] and '5일 전' in comparison['after']['text']
        checks['applied_v2_offline'] = '5일 전' in answer2['answer'] and '3일 전' not in answer2['answer'] and not answer2['guidance']['ai_used'] and answer2['model'] is None
        checks['wrong_institution_excluded'] = not any(e.get('reference_kind')=='institution_rule' for e in ask('다른 기관')['knowledge']['evidence'])
        original_checks=[]
        for version,raw in zip(doc['versions'],[v1,v2]):
            original=c.get(prefix+'/versions/'+version['id']+'/original');original.raise_for_status()
            file=c.get(prefix+'/versions/'+version['id']+'/file');file.raise_for_status()
            original_checks.append(original.text==version['text'] and hashlib.sha256(file.content).hexdigest()==hashlib.sha256(raw).hexdigest())
        checks['both_original_text_and_files_preserved'] = all(original_checks)
        doc=req('PATCH',prefix,json={'revision':doc['revision'],'operation':'disable'})
        checks['disabled_not_answered'] = not any(e.get('reference_kind')=='institution_rule' for e in ask()['knowledge']['evidence'])
        doc=req('PATCH',prefix,json={'revision':doc['revision'],'operation':'delete'})
        checks['deleted_hidden_but_recoverable'] = not req('GET','/api/institution-rules')['items'] and len(req('GET','/api/institution-rules?include_deleted=true')['items'])==1
        checks['deleted_original_still_open'] = c.get(prefix+'/versions/'+doc['versions'][0]['id']+'/original').text==doc['versions'][0]['text']
        doc=req('PATCH',prefix,json={'revision':doc['revision'],'operation':'restore'})
        checks['restore_disabled_versions_and_history'] = not doc['enabled'] and not doc['deleted'] and len(doc['versions'])==2 and len(doc['events'])==7
        checks['sample_files_unchanged'] = (samples/'제출기한_v1.txt').read_bytes()==v1 and (samples/'제출기한_v2.txt').read_bytes()==v2
        assert all(checks.values()), checks
        return dict(passed=True,created_at=datetime.now(timezone.utc).isoformat(),checks=checks,
                    actual_model_calls=0,status=status,document=doc,answer_v1=answer1,
                    answer_v2_draft=answer_draft2,answer_v2=answer2,comparison=comparison)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base',required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();report=run(args.base.rstrip('/'))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':True,'checks':len(report['checks']),'document_id':report['document']['id']},ensure_ascii=False))
