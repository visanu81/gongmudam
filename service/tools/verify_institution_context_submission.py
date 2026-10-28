"""Reproduce affiliation-aware, AI-off questions in a fresh private installation."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]

def run(base):
    if not (ROOT/'data/submission-installation.json').is_file():
        raise RuntimeError('Use a separate restored submission installation')
    release=json.loads((ROOT/'submission-manifest.json').read_text(encoding='utf-8'))['release_version']
    checks={};answers={};created=[];originals={}
    with httpx.Client(base_url=base,headers={'Origin':base},timeout=45) as c:
        def req(method,path,expected=200,**kwargs):
            response=c.request(method,path,**kwargs)
            if response.status_code!=expected:raise AssertionError(f'{method} {path}: {response.status_code} {response.text[:300]}')
            return response.json()
        status=req('GET','/api/gongmudam/status')
        assert not status['public_demo'] and status['service_version']==release
        assert not req('GET','/api/institution-rules?include_deleted=true')['items'],'Use a fresh test installation without institution documents'
        checks['default_offline']=req('GET','/api/settings')['llm']['active']=='offline'
        sources=req('GET','/api/knowledge/sources')
        expected_sources=json.loads((ROOT/'submission-data/knowledge.json').read_text(encoding='utf-8'))['sources']
        expected_ids={s.get('id') for s in expected_sources}
        actual_ids={s.get('id') for s in sources}
        checks['bundled_sources_current']=(
            len(sources)==len(expected_sources) and len(expected_ids)==len(expected_sources) and
            actual_ids==expected_ids and all(s['current'] and s['enabled'] for s in sources))
        checks['manuals_6_pages_221']=sum(s.get('reference_kind')=='system_manual' for s in sources)==6 and sum(s.get('page_count',0) for s in sources)==221
        checks['all_originals_inside_installation']=all(Path(s['path']).resolve().is_relative_to(ROOT.resolve()) for s in sources)
        config_hash=hashlib.sha256((ROOT/'config.json').read_bytes()).hexdigest()
        samples=ROOT/'sample_data/institution-rules-v78'
        sample_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in samples.glob('*.txt')}
        profile=dict(confirmed=True,organization='합성 제출검증기관',personnel_framework='national_public_official',region='서울특별시',department='합성 검증')

        def upload(filename,**fields):
            fields={'institution':profile['organization'],'kind':'기관 지침','category':'교육·행사',
                    'keywords':json.dumps(['연수 신청 접수'],ensure_ascii=False),'effective_date':'2026-01-01',
                    'scope_notes':'실제 기관 업무에 적용하지 않는 합성 제출 검증 자료',**fields}
            doc=req('POST','/api/institution-rules/upload',201,data=fields,files={'file':(filename,(samples/filename).read_bytes(),'text/plain')})
            if doc['id'] not in created:created.append(doc['id'])
            return doc
        def apply(doc):
            version=doc['versions'][-1];prefix='/api/institution-rules/'+doc['id']
            comparison=req('GET',prefix+'/compare',params={'from_version':doc.get('active_version_id') or '', 'to_version':version['id']})
            return req('PATCH',prefix,json=dict(operation='apply',revision=comparison['revision'],version_id=version['id'],reviewed_sha256=version['sha256'])),comparison
        def ask(name,query,**extra):
            body=dict(query=query,guidance=True,use_ai=False,today='2026-10-26',affiliation=profile);body.update(extra)
            answer=req('POST','/api/ask',json=body);answers[name]=answer
            assert not answer['guidance']['ai_used'] and answer.get('model') is None
            assert answer['guidance']['context']==query
            return answer
        def managed(answer):return [h for h in answer['knowledge']['evidence'] if h.get('reference_kind')=='institution_rule']
        def no_managed(answer):return not managed(answer)
        try:
            form=upload('교육참가_신청서.txt',title='[합성 예제] 교육참가 신청서',kind='서식',keywords=json.dumps(['교육참가 신청서'],ensure_ascii=False))
            form,_=apply(form)
            policy=upload('연수_참가_접수_v1.txt',title='[합성 예제] 연수 참가 접수 안내')
            query='교육에 참여하려는데 언제까지 내야 해요?'
            draft=ask('draft',query)
            checks['draft_excluded']=no_managed(draft)
            policy,_=apply(policy);prefix='/api/institution-rules/'+policy['id']
            answer=ask('v1',query)
            checks['natural_question_own_affiliation']='3일 전' in answer['answer'] and {h['source_id'] for h in managed(answer)}=={policy['source_id']}
            checks['affiliation_label']=answer['guidance']['institution_scope']['basis']=='affiliation'
            checks['applied_form_link']=any(f.get('source_id')==form['source_id'] and f.get('version_number')==1 for f in answer['guidance']['forms'])
            paraphrase=ask('paraphrase','연수 참석자 마감이 언제인가요?')
            checks['alternate_words']='3일 전' in paraphrase['answer']
            follow=ask('form-followup','그럼 어떤 양식을 쓰면 돼요?',situation_context=query)
            checks['followup_form']=any(f.get('source_id')==form['source_id'] for f in follow['guidance']['forms'])
            fields=ask('fields-followup','그럼 어떤 항목을 적어야 하나요?',situation_context=query+'\n그럼 어떤 양식을 쓰면 돼요?')
            checks['followup_fields_without_prior_deadline']='연락처' in fields['answer'] and {h['source_id'] for h in managed(fields)}=={form['source_id']}
            checks['missing_affiliation_not_guessed']=no_managed(ask('no-affiliation',query,affiliation=None))
            checks['unconfirmed_affiliation_not_guessed']=no_managed(ask('unconfirmed',query,affiliation=profile|{'confirmed':False}))
            checks['wrong_agency_not_substituted']=no_managed(ask('wrong-agency','없는시청 교육 마감은?'))
            checks['unknown_subject_not_substituted']=no_managed(ask('copyright','교육 저작권은?'))
            checks['explicit_name_does_not_bypass_relevance']=no_managed(ask('explicit-copyright',profile['organization']+' 교육 저작권은?'))
            old=policy['versions'][0]
            policy=upload('연수_참가_접수_v2.txt',title=policy['title'],rule_id=policy['id'],revision=str(policy['revision']),change_note='합성 기한 3일 전 → 5일 전')
            unapproved=ask('v2-draft',query)
            checks['unapplied_v2_keeps_v1']='3일 전' in unapproved['answer'] and '5일 전' not in unapproved['answer']
            policy,comparison=apply(policy)
            v2=ask('v2',query)
            checks['v2_apply_changes_answer']='5일 전' in v2['answer'] and '3일 전' not in v2['answer']
            checks['comparison_before_after']='3일 전' in comparison['before']['text'] and '5일 전' in comparison['after']['text']
            checks['historical_original_preserved']=c.get(prefix+'/versions/'+old['id']+'/original').text==old['text']
            # A category-only revision also needs explicit application.
            previous=policy['versions'][-1]
            body={k:previous[k] for k in ('title','institution','kind','keywords','text','effective_date','scope_notes')}
            updated=req('POST',prefix+'/versions',201,json=body|dict(category='기타',revision=policy['revision'],change_note='합성 분류 변경'))
            checks['category_draft_keeps_applied_category']=updated['category']=='교육·행사'
            policy,comparison=apply(updated)
            checks['category_change_versioned']=policy['category']=='기타' and any(d['field']=='category' for d in comparison['metadata_changes']) and policy['versions'][0]['category']=='교육·행사'
            checks['category_catalog_9']=len(req('GET','/api/institution-rules')['categories'])==9
            # Parent, child, and an unregistered council are distinct scopes.
            parent=upload('연수_참가_접수_v1.txt',title='[합성 예제] 부모 기관 교육 안내',institution='부산광역시');parent,_=apply(parent)
            child=upload('연수_참가_접수_v2.txt',title='[합성 예제] 교육청 교육 안내',institution='부산광역시교육청');child,_=apply(child)
            child_answer=ask('child-agency','부산광역시교육청 교육 마감은?',affiliation=profile|{'organization':'부산광역시'})
            checks['child_agency_not_parent']={h['source_id'] for h in managed(child_answer)}=={child['source_id']} and '5일 전' in child_answer['answer']
            checks['unregistered_council_not_parent']=no_managed(ask('council','부산광역시의회 교육 마감은?',affiliation=profile|{'organization':'부산광역시'}))
            checks['no_personnel_inference_from_other_agency']='업무환경: 국가공무원' not in child_answer['query']
            core={
                'child-care':'아이가 아파서 돌봐야 하는데 어떤 휴가를 써요?',
                'health-check':'건강검진을 받으려는데 공가를 쓸 수 있나요?',
                'travel':'출장 때 공용차량을 타면 일비는 어떻게 되나요?',
                'budget':'사무용품을 사려는데 무슨 목으로 구입해야 하나요?',
            }
            for name,q in core.items():
                result=ask(name,q)
                checks['common_'+name]=bool(result['knowledge']['evidence']) and not managed(result)
            for key,value in answers.items():
                for h in managed(value):
                    url=f"/api/institution-rules/{h['managed_rule_id']}/versions/{h['managed_version_id']}/original"
                    response=c.get(url);response.raise_for_status()
                    assert h['quote'] in response.text and hashlib.sha256(response.content).hexdigest()==h['sha256'],key
                    originals[url]=h['sha256']
            checks['quotes_versions_and_sha_match']=bool(originals)
            checks['config_unchanged']=hashlib.sha256((ROOT/'config.json').read_bytes()).hexdigest()==config_hash
            checks['sample_files_unchanged']=sample_hashes=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in samples.glob('*.txt')}
        finally:
            for key in created:
                doc=req('GET','/api/institution-rules/'+key)
                if doc['enabled']:req('PATCH','/api/institution-rules/'+key,json=dict(operation='disable',revision=doc['revision'],note='합성 제출 검증 완료'))
        checks['all_synthetic_inactive']=all(not req('GET','/api/institution-rules/'+key)['enabled'] for key in created)
        return dict(passed=all(checks.values()),release_version=release,created_at=datetime.now(timezone.utc).isoformat(),
            environment='Same Windows PC; separate extracted ZIP, new venv and runtime DB; not a second physical PC',
            actual_model_calls=0,checks=checks,answers=answers,verified_originals=originals,
            documents=[req('GET','/api/institution-rules/'+key) for key in created],config_sha256=config_hash)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base',required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();report=run(args.base.rstrip('/'))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(passed=report['passed'],checks=len(report['checks']),questions=len(report['answers']),actual_model_calls=0),ensure_ascii=False))
    raise SystemExit(0 if report['passed'] else 1)
