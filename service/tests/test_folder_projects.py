import json
from pathlib import Path
import tempfile
import threading
import time
import tracemalloc
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import folders, folder_projects as projects, config, project_text


class FolderProjectsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [patch.object(folders, 'DB_PATH', self.root/'folders.db'),
                        patch.object(config, 'active_profile', return_value={'provider':'offline', '_name':'offline'})]
        for p in self.patches:
            p.start()
        folders.initialize()
        projects.initialize()
        self.app = FastAPI()
        self.app.include_router(projects.router)
        self.client = TestClient(self.app, client=('127.0.0.1', 1234), base_url='http://127.0.0.1:9988')
        self.headers = {'origin':'http://127.0.0.1:9988'}
        self.worker = None
        self.parse = patch.object(projects, 'parse_file', side_effect=lambda path,tick: project_text.extract(path))
        self.parse.start()

    def tearDown(self):
        if self.worker:
            self.worker.stop()
        self.parse.stop()
        self.client.close()
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def create(self, name='교육 준비'):
        r = self.client.post('/api/folder-projects', json={'name':name})
        self.assertEqual(r.status_code,201,r.text)
        return r.json()['id']

    def source(self, pid, path, kind='folder'):
        r = self.client.post(f'/api/folder-projects/{pid}/sources', json={'kind':kind,'paths':[str(path)]}, headers=self.headers)
        self.assertEqual(r.status_code,202,r.text)
        return r.json()

    def start(self):
        self.worker = projects.Worker().start()

    def wait(self, pid, predicate, timeout=8):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            value=self.client.get(f'/api/folder-projects/{pid}').json()
            if predicate(value):
                return value
            time.sleep(.03)
        self.fail('대기 시간 초과: '+json.dumps(value,ensure_ascii=False))

    def question(self,pid,content,**kwargs):
        r=self.client.post(f'/api/folder-projects/{pid}/messages',json={'content':content,**kwargs})
        self.assertEqual(r.status_code,202,r.text)
        return r.json()

    def answered(self,pid):
        return self.wait(pid,lambda v:v['messages'] and v['messages'][-1]['status']=='completed')

    def test_detail_keeps_files_and_job_status_in_one_snapshot(self):
        pid=self.create()
        with projects.db() as c:
            c.execute('PRAGMA journal_mode=WAL')
            projects.put(c,'project_jobs',{'id':'snapshot-job','project_id':pid,'status':'running'})
        original_rows=projects.rows
        changed=False
        def concurrent_commit(c,table,key):
            nonlocal changed
            result=original_rows(c,table,key)
            if table=='project_files' and not changed:
                changed=True
                with projects.db() as writer:
                    projects.put(writer,'project_files',{'id':'snapshot-file','project_id':pid,'name':'교육 안내.txt',
                                 'path':str(self.root/'not-present.txt'),'root':str(self.root)})
                    projects.put(writer,'project_jobs',{'id':'snapshot-job','project_id':pid,'status':'completed'})
            return result
        with projects.db() as c, patch.object(projects,'rows',side_effect=concurrent_commit):
            snapshot=projects.detail(c,pid)
        self.assertEqual(snapshot['files'],[])
        self.assertEqual(snapshot['jobs'][0]['status'],'running')
        with projects.db() as c:
            current=projects.detail(c,pid)
        self.assertEqual(current['files'][0]['id'],'snapshot-file')
        self.assertEqual(current['jobs'][0]['status'],'completed')

    def test_create_before_read_queue_question_citations_and_draft_persist(self):
        folder=self.root/'교육';folder.mkdir()
        original=folder/'교육안내.txt';original.write_text('교육 회신 마감은 2026-11-06입니다.\n참석 대상은 총무과와 회계과입니다.',encoding='utf-8')
        before=original.read_bytes()
        pid=self.create()
        self.assertTrue(self.client.get('/api/folder-projects').json()['local_access'])
        self.source(pid,folder)
        self.question(pid,'교육 회신 마감은 언제인가요?')
        self.start()
        v=self.answered(pid);answer=v['messages'][-1]
        self.assertIn('2026-11-06',answer['content']);self.assertEqual(answer['mode'],'offline')
        evidence=answer['evidence'][0]
        unit=self.client.get(f"/api/folder-projects/{pid}/files/{evidence['file_id']}/units/{evidence['unit']}")
        self.assertEqual(unit.json()['text'],evidence['text'])
        self.question(pid,'보고서 초안을 작성해줘',draft=True)
        v=self.answered(pid);mid=v['messages'][-1]['id']
        r=self.client.patch(f'/api/folder-projects/{pid}/messages/{mid}',json={'content':'담당자가 검토한 초안'})
        self.assertEqual(r.status_code,200)
        projects.initialize(recover=True)
        self.assertEqual(self.client.get(f'/api/folder-projects/{pid}').json()['messages'][-1]['content'],'담당자가 검토한 초안')
        self.assertEqual(original.read_bytes(),before)

    def test_remove_file_folder_and_restore_never_touch_originals(self):
        folder=self.root/'교육';folder.mkdir()
        keep=folder/'안내.txt';keep.write_text('교육 회신 마감은 11월 6일입니다.',encoding='utf-8')
        drop=folder/'메모.txt';drop.write_text('행사 예산은 123만원입니다.',encoding='utf-8')
        single=self.root/'단독.txt';single.write_text('단독 파일 내용입니다.',encoding='utf-8')
        pid=self.create();self.source(pid,folder);self.source(pid,single,'file');self.start()
        v=self.wait(pid,lambda v:v['jobs'][-1]['status']=='completed' and len(v['files'])==3)
        self.assertNotIn('path',v['sources'][0])
        memo=next(f for f in v['files'] if f['name']=='메모.txt')
        v=self.client.delete(f'/api/folder-projects/{pid}/files/{memo["id"]}').json()
        self.assertEqual(sorted(f['name'] for f in v['files']),['단독.txt','안내.txt'])
        self.assertEqual([e['name'] for e in v['excluded']],['메모.txt'])
        self.assertNotIn(str(folder),json.dumps(v['excluded'],ensure_ascii=False))
        # A later read of the folder keeps the excluded file out.
        self.client.post(f'/api/folder-projects/{pid}/refresh')
        v=self.wait(pid,lambda v:v['jobs'][-1]['status']=='completed')
        self.assertNotIn('메모.txt',[f['name'] for f in v['files']])
        self.question(pid,'행사 예산은 얼마인가요?')
        self.assertFalse(self.answered(pid)['messages'][-1]['evidence'])
        # Putting it back reads it again.
        self.client.post(f'/api/folder-projects/{pid}/excluded/restore',json={'id':v['excluded'][0]['id']})
        v=self.wait(pid,lambda v:v['jobs'][-1]['status']=='completed' and len(v['files'])==3)
        self.assertEqual(v['excluded'],[])
        # Removing a single-file source removes the source too; removing the folder removes its files.
        lone=next(f for f in v['files'] if f['name']=='단독.txt')
        v=self.client.delete(f'/api/folder-projects/{pid}/files/{lone["id"]}').json()
        self.assertEqual([s['kind'] for s in v['sources']],['folder'])
        v=self.client.delete(f'/api/folder-projects/{pid}/sources/{v["sources"][0]["id"]}').json()
        self.assertEqual((v['sources'],v['files']),([],[]))
        for path in (keep,drop,single):self.assertTrue(path.exists())

    def test_new_extractor_rereads_files_and_marks_old_citations_changed(self):
        a=self.root/'a.txt';a.write_text('교육 회신 마감은 11월 6일입니다.',encoding='utf-8')
        pid=self.create();self.source(pid,a,'file');self.start()
        self.wait(pid,lambda v:v['jobs'][-1]['status']=='completed')
        self.question(pid,'회신 마감은 언제인가요?')
        answer=self.answered(pid)['messages'][-1]
        self.assertFalse(answer['evidence'][0]['stale'])
        with patch.object(project_text,'EXTRACTOR_VERSION','next-extractor'):
            self.client.post(f'/api/folder-projects/{pid}/refresh')
            v=self.wait(pid,lambda v:v['files'][0].get('extractor')=='next-extractor' and v['jobs'][-1]['status']=='completed')
        self.assertTrue(v['messages'][-1]['evidence'][0]['stale'])

    def test_removal_waits_for_a_running_read(self):
        a=self.root/'a.txt';a.write_text('내용',encoding='utf-8')
        pid=self.create();v=self.source(pid,a,'file')
        r=self.client.delete(f'/api/folder-projects/{pid}/sources/{v["sources"][0]["id"]}')
        self.assertEqual(r.status_code,409)

    def test_outputs_panel_keeps_and_drops_answers(self):
        a=self.root/'a.txt';a.write_text('교육 회신 마감은 11월 6일입니다.\n참석 대상은 총무과입니다.',encoding='utf-8')
        pid=self.create();self.source(pid,a,'file');self.start()
        self.wait(pid,lambda v:v['jobs'][-1]['status']=='completed')
        self.question(pid,'요약',output=True)
        answer=self.answered(pid)['messages'][-1]
        self.assertTrue(answer['output'])
        self.question(pid,'회신 마감은 언제인가요?')
        plain=self.answered(pid)['messages'][-1]
        self.assertFalse(plain.get('output'))
        v=self.client.post(f'/api/folder-projects/{pid}/messages/{plain["id"]}/output',json={'saved':True}).json()
        self.assertTrue(v['messages'][-1]['output'])
        v=self.client.post(f'/api/folder-projects/{pid}/messages/{answer["id"]}/output',json={'saved':False}).json()
        self.assertFalse(next(m for m in v['messages'] if m['id']==answer['id'])['output'])
        user=next(m for m in v['messages'] if m['role']=='user')
        self.assertEqual(self.client.post(f'/api/folder-projects/{pid}/messages/{user["id"]}/output',json={'saved':True}).status_code,422)

    def test_project_and_explicit_file_scope_are_isolated(self):
        a=self.root/'a.txt';a.write_text('교육 회신 마감은 11월 6일입니다.',encoding='utf-8')
        b=self.root/'b.txt';b.write_text('행사 예산은 123만원입니다.',encoding='utf-8')
        p1,p2=self.create('교육'),self.create('행사')
        self.source(p1,a,'file');self.source(p2,b,'file');self.start()
        self.wait(p1,lambda v:v['jobs'][-1]['status']=='completed')
        self.wait(p2,lambda v:v['jobs'][-1]['status']=='completed')
        self.question(p1,'행사 예산은 얼마인가요?')
        self.assertFalse(self.answered(p1)['messages'][-1]['evidence'])
        foreign=self.client.get(f'/api/folder-projects/{p2}').json()['files'][0]['id']
        self.assertEqual(self.client.post(f'/api/folder-projects/{p1}/messages',json={'content':'예산','file_ids':[foreign]}).status_code,422)
        self.assertEqual(self.client.get(f'/api/folder-projects/{p1}/files/{foreign}/units/1').status_code,404)

    def test_natural_question_finds_status_without_inventing_department_label(self):
        folder=self.root/'교육';folder.mkdir()
        (folder/'회신 현황.txt').write_text('총무과: 회신 완료\n회계과: 미회신\n교육 회신 마감: 2026-11-06 18:00',encoding='utf-8')
        pid=self.create();self.source(pid,folder);self.start()
        self.wait(pid,lambda v:v['jobs'][-1]['status']=='completed')
        for question in ('미회신 부서는 어디인가요?', '어느 부서가 아직 회신하지 않았나요?', '회신 안 한 부서를 알려주세요'):
            with self.subTest(question=question):
                self.question(pid,question);answer=self.answered(pid)['messages'][-1]
                self.assertEqual(answer['mode'],'offline')
                self.assertTrue(answer['evidence'],answer['content'])
                self.assertIn('회계과: 미회신',answer['content'])
                self.assertNotIn('총무과: 회신 완료',answer['content'])
                e=answer['evidence'][0]
                self.assertEqual(e['loc'],'2행')
                self.assertEqual(self.client.get(f"/api/folder-projects/{pid}/files/{e['file_id']}/units/{e['unit']}").json()['text'],e['text'])

    def test_natural_status_search_keeps_topic_selection_and_no_evidence_guards(self):
        folder=self.root/'자료';folder.mkdir()
        (folder/'교육 현황.txt').write_text('회계과: 미회신\n총무과: 회신 완료',encoding='utf-8')
        (folder/'행사 현황.txt').write_text('복지과: 미회신',encoding='utf-8')
        pid=self.create('자료 모음');self.source(pid,folder);self.start()
        self.wait(pid,lambda v:v['jobs'][-1]['status']=='completed')
        self.question(pid,'교육 미회신 부서는 어디인가요?')
        answer=self.answered(pid)['messages'][-1]
        self.assertIn('회계과',answer['content']);self.assertNotIn('복지과',answer['content'])
        selected=next(f['id'] for f in self.client.get(f'/api/folder-projects/{pid}').json()['files'] if f['name']=='행사 현황.txt')
        for q,kwargs in (('교육 미회신 부서는 어디인가요?',{'file_ids':[selected]}),('출장 미회신 부서는 어디인가요?',{}),('항공권 취소 수수료는 얼마인가요?',{}),('어디인가요?',{})):
            with self.subTest(q=q,kwargs=kwargs):
                self.question(pid,q,**kwargs)
                self.assertFalse(self.answered(pid)['messages'][-1]['evidence'])

    def test_reply_delivery_is_not_pending_and_page_excerpt_keeps_status_rows(self):
        f=self.root/'현황.txt';f.write_text('회계과: 회신 전달 완료\n총무과: 회신 전화로 완료',encoding='utf-8')
        pid=self.create();self.source(pid,f,'file');self.start()
        self.wait(pid,lambda v:v['jobs'][-1]['status']=='completed')
        self.question(pid,'미회신 부서는 어디인가요?')
        self.assertFalse(self.answered(pid)['messages'][-1]['evidence'])
        page='부서별 현황\n교육 회신 마감: 11월 6일\n총무과: 회신 완료\n회계과: 미회신\n복지과: 미회신'
        with projects.db() as c:
            fid=projects.rows(c,'project_files',pid)[0]['id']
            c.execute('DELETE FROM project_units WHERE file_id=?',(fid,))
            c.execute('INSERT INTO project_units VALUES(?,?,?,?)',(fid,1,'PDF 1쪽',page))
        self.question(pid,'미회신 부서는 어디인가요?');answer=self.answered(pid)['messages'][-1]
        self.assertIn('회계과: 미회신',answer['content']);self.assertIn('복지과: 미회신',answer['content'])
        self.assertNotIn('총무과: 회신 완료',answer['content'])
        self.assertEqual(answer['evidence'][0]['loc'],'PDF 1쪽')
        self.assertEqual(answer['evidence'][0]['text'],page)
        self.question(pid,'교육 회신 마감과 미회신 부서는?');answer=self.answered(pid)['messages'][-1]
        self.assertIn('11월 6일',answer['content']);self.assertIn('회계과: 미회신',answer['content'])

    def test_source_changes_reindex_and_preserve_previous_answer(self):
        a=self.root/'교육.txt';a.write_text('교육 마감은 11월 6일입니다.',encoding='utf-8')
        pid=self.create();self.source(pid,a,'file');self.start()
        self.question(pid,'교육 마감');v=self.answered(pid)
        old=v['messages'][-1]['content'];fid=v['files'][0]['id']
        a.write_text('교육 마감은 11월 16일로 변경되었습니다.',encoding='utf-8')
        self.assertTrue(self.client.get(f'/api/folder-projects/{pid}').json()['messages'][-1]['evidence'][0]['stale'])
        self.assertEqual(self.client.get(f'/api/folder-projects/{pid}/files/{fid}/original').status_code,409)
        self.client.post(f'/api/folder-projects/{pid}/refresh')
        self.wait(pid,lambda v:all(j['status']=='completed' for j in v['jobs']))
        self.question(pid,'교육 마감');v=self.answered(pid)
        self.assertIn('11월 16일',v['messages'][-1]['content'])
        self.assertEqual(v['messages'][1]['content'],old)
        self.assertTrue(v['messages'][1]['evidence'][0]['stale'])

    def test_cancel_failure_and_restart_keep_question(self):
        f=self.root/'x.txt';f.write_text('일정: 11월 6일',encoding='utf-8')
        pid=self.create();v=self.source(pid,f,'file');jid=v['jobs'][0]['id']
        self.question(pid,'일정')
        self.client.post(f'/api/folder-projects/{pid}/jobs/{jid}/cancel')
        projects.initialize(recover=True);self.start()
        v=self.answered(pid)
        self.assertEqual(v['jobs'][0]['status'],'cancelled')
        self.assertIn('직접 근거',v['messages'][-1]['content'])

    def test_add_source_during_read_gets_followup_job(self):
        a=self.root/'a.txt';a.write_text('교육 일정: 11월 6일',encoding='utf-8')
        b=self.root/'b.txt';b.write_text('교육 대상: 총무과',encoding='utf-8')
        entered=threading.Event();release=threading.Event()
        def slow(path,tick):
            if path==a:
                entered.set();release.wait(3)
            return project_text.extract(path)
        with patch.object(projects,'parse_file',side_effect=slow):
            pid=self.create();self.source(pid,a,'file');self.start()
            self.assertTrue(entered.wait(3))
            self.source(pid,b,'file');self.question(pid,'핵심 내용 요약')
            release.set();v=self.answered(pid)
            self.assertEqual(len(v['files']),2)
            self.assertEqual(len(v['messages'][-1]['evidence']),2)

    def test_selected_ready_file_answers_while_other_file_reads(self):
        folder=self.root/'교육';folder.mkdir()
        (folder/'a.txt').write_text('교육 일정: 11월 6일',encoding='utf-8')
        (folder/'b.txt').write_text('교육 대상: 총무과',encoding='utf-8')
        entered=threading.Event();release=threading.Event()
        def slow(path,tick):
            if path.name=='a.txt':
                entered.set();release.wait(3)
            return project_text.extract(path)
        with patch.object(projects,'parse_file',side_effect=slow):
            pid=self.create();self.source(pid,folder);self.start();self.assertTrue(entered.wait(3))
            v=self.client.get(f'/api/folder-projects/{pid}').json()
            fid=next(f['id'] for f in v['files'] if f['name']=='a.txt')
            self.question(pid,'교육 일정',file_ids=[fid]);release.set()
            self.assertEqual(len(self.answered(pid)['messages'][-1]['evidence']),1)

    def test_import_preserves_old_classification_and_is_idempotent(self):
        folder=self.root/'업무';folder.mkdir();(folder/'a.txt').write_text('업무명: 교육\n연도: 2026',encoding='utf-8')
        old=folders.connect(folders.Connect(name='기존 자료',roots=[str(folder)]))
        with folders.db() as c:before=c.execute('SELECT payload FROM libraries WHERE id=?',(old['id'],)).fetchone()[0]
        r=self.client.post('/api/folder-projects/import-library',json={'library_id':old['id']})
        self.assertEqual(r.status_code,201,r.text)
        r2=self.client.post('/api/folder-projects/import-library',json={'library_id':old['id']})
        self.assertEqual(r.json()['id'],r2.json()['id'])
        with folders.db() as c:self.assertEqual(c.execute('SELECT payload FROM libraries WHERE id=?',(old['id'],)).fetchone()[0],before)

    def test_public_and_tunnel_cannot_add_pc_paths_or_open_picker(self):
        pid=self.create();folder=self.root/'private';folder.mkdir()
        self.app.state.public_demo=True
        self.assertFalse(self.client.get('/api/folder-projects').json()['local_access'])
        self.assertEqual(self.client.post(f'/api/folder-projects/{pid}/sources',json={'kind':'folder','paths':[str(folder)]},headers=self.headers).status_code,403)
        self.assertEqual(self.client.post('/api/folder-projects/choose-files',headers=self.headers).status_code,403)
        self.app.state.public_demo=False
        headers=self.headers|{'x-forwarded-for':'203.0.113.1'}
        self.assertEqual(self.client.post(f'/api/folder-projects/{pid}/sources',json={'kind':'folder','paths':[str(folder)]},headers=headers).status_code,403)

    def test_two_local_models_choose_only_known_evidence_and_fallback(self):
        f=self.root/'교육.txt';f.write_text('교육 회신 마감은 11월 6일입니다.',encoding='utf-8')
        pid=self.create();self.source(pid,f,'file');self.start()
        self.wait(pid,lambda v:v['jobs'][-1]['status']=='completed')
        for model in ('gemma3:4b','llama3.2:3b'):
            with patch.object(config,'active_profile',return_value={'provider':'openai_compatible','_name':'local'}),patch.object(projects.local_ai,'local_profile',return_value={'model':model,'base_url':'http://127.0.0.1:11434/v1'}),patch.object(projects.folder_ai,'call_model',return_value=('{"refs":[1]}',{'actual_response':True,'response_model':model})):
                self.question(pid,'교육 마감');v=self.answered(pid)
                self.assertEqual(v['messages'][-1]['model'],model)
                self.assertEqual(v['messages'][-1]['mode'],'local_ai')
        with patch.object(config,'active_profile',return_value={'provider':'openai_compatible','_name':'local'}),patch.object(projects.local_ai,'local_profile',return_value={'model':'bad','base_url':'http://127.0.0.1:11434/v1'}),patch.object(projects.folder_ai,'call_model',return_value=('{"refs":[999]}',{})):
            self.question(pid,'교육 마감');self.assertEqual(self.answered(pid)['messages'][-1]['mode'],'fallback')

    def contest(self):
        folder=self.root/'대회';folder.mkdir()
        (folder/'챌린지 행사계획 안내서.txt').write_text('2026 공공 AI 챌린지 행사계획(가상)\n접수 기간: 2026-11-01 ~ 2026-11-10\n시상: 최우수 1팀 상장',encoding='utf-8')
        (folder/'참가신청서.txt').write_text('참가신청서(합성)\n소속: 가람시 총무과\n성명: 홍길동',encoding='utf-8')
        pid=self.create('대회 준비');self.source(pid,folder);self.start()
        self.wait(pid,lambda v:v['jobs'] and all(j['status']=='completed' for j in v['jobs']))
        return pid

    def test_everyday_words_find_what_the_form_calls_them(self):
        # "참가한 사람" is written as 성명 on the form, "대회" as 챌린지 on the notice.
        pid=self.contest()
        self.question(pid,'이 대회에 참가한 사람은?');answer=self.answered(pid)['messages'][-1]
        self.assertIn('홍길동',' '.join(e['text'] for e in answer['evidence']))

    def test_model_chooses_from_all_files_when_no_word_matches(self):
        pid=self.contest()
        def choose(profile,messages,schema=None,strict=False):
            docs=json.loads(messages[-1]['content'])['documents']
            return json.dumps({'refs':[d['ref'] for d in docs if '시상' in d['text']]}),{'actual_response':True}
        local=dict(provider='openai_compatible',_name='local')
        with patch.object(config,'active_profile',return_value=local),patch.object(projects.local_ai,'local_profile',return_value={'model':'t','base_url':'http://127.0.0.1:11434/v1'}),patch.object(projects.folder_ai,'call_model',side_effect=choose):
            self.question(pid,'우승하면 무엇을 받아?');answer=self.answered(pid)['messages'][-1]
        self.assertEqual(answer['mode'],'local_ai')
        self.assertEqual([e['text'] for e in answer['evidence']],['시상: 최우수 1팀 상장'])
        self.assertIn('AI가 자료 전체에서',answer['notice'])
        # Nothing from the spread is shown when the model chooses nothing.
        with patch.object(config,'active_profile',return_value=local),patch.object(projects.local_ai,'local_profile',return_value={'model':'t','base_url':'http://127.0.0.1:11434/v1'}),patch.object(projects.folder_ai,'call_model',return_value=('{"refs":[]}',{})):
            self.question(pid,'우승하면 무엇을 받아?');answer=self.answered(pid)['messages'][-1]
        self.assertEqual(answer['evidence'],[])
        # Without AI the answer stays a plain "not found".
        self.question(pid,'우승하면 무엇을 받아?');answer=self.answered(pid)['messages'][-1]
        self.assertEqual((answer['mode'],answer['evidence']),('offline',[]))

    def test_followup_keeps_previous_scope_and_summary_includes_each_file(self):
        folder=self.root/'자료';folder.mkdir()
        for i in range(6):
            (folder/f'{i}.txt').write_text(f'교육 {i}번 자료입니다.\n회신 기한: 11월 {i+1}일\n담당 부서: {i}과',encoding='utf-8')
        pid=self.create();self.source(pid,folder);self.start()
        self.question(pid,'전체 자료 비교');v=self.answered(pid)
        self.assertEqual(len({e['file_id'] for e in v['messages'][-1]['evidence']}),6)
        chosen=v['files'][0]['id']
        self.question(pid,'핵심 내용 요약',file_ids=[chosen]);self.answered(pid)
        self.question(pid,'그걸 요약해줘');v=self.answered(pid)
        self.assertEqual({e['file_id'] for e in v['messages'][-1]['evidence']},{chosen})

    def test_auto_detect_changes_but_does_not_restart_cancelled_read(self):
        f=self.root/'교육.txt';f.write_text('교육 마감: 11월 6일',encoding='utf-8')
        pid=self.create();self.source(pid,f,'file');self.start()
        self.wait(pid,lambda v:v['jobs'][-1]['status']=='completed')
        f.write_text('교육 마감: 11월 16일',encoding='utf-8')
        self.worker.check_sources()
        self.wait(pid,lambda v:len(v['jobs'])==2 and v['jobs'][-1]['status']=='completed')
        self.worker.stop();self.worker=None
        v=self.client.post(f'/api/folder-projects/{pid}/refresh').json();jid=v['jobs'][-1]['id']
        self.client.post(f'/api/folder-projects/{pid}/jobs/{jid}/cancel')
        f.write_text('교육 마감: 11월 26일',encoding='utf-8')
        checker=projects.Worker();checker.check_sources()
        after=self.client.get(f'/api/folder-projects/{pid}').json()
        self.assertEqual(len(after['jobs']),3);self.assertEqual(after['jobs'][-1]['status'],'cancelled')

    def test_summary_search_retains_bounded_context_for_large_text(self):
        f=self.root/'긴 자료.txt';f.write_text('본문',encoding='utf-8')
        pid=self.create();self.source(pid,f,'file');self.start()
        self.wait(pid,lambda v:v['jobs'][-1]['status']=='completed')
        self.worker.stop();self.worker=None
        with projects.db() as c:
            fid=projects.rows(c,'project_files',pid)[0]['id']
            c.execute('DELETE FROM project_units WHERE file_id=?',(fid,))
            c.executemany('INSERT INTO project_units VALUES(?,?,?,?)',((fid,i,f'{i}행','가'*1700) for i in range(1,10001)))
        tracemalloc.start()
        try:
            with projects.db() as c:result=projects.retrieve(c,pid,'전체 자료 요약',[])
            self.assertLess(tracemalloc.get_traced_memory()[1],8_000_000)
            self.assertLessEqual(len(result),24)
        finally:tracemalloc.stop()

    def test_model_cannot_omit_direct_evidence_for_second_question_part(self):
        folder=self.root/'복합질문';folder.mkdir()
        (folder/'안내.txt').write_text('교육 회신 마감은 11월 6일입니다.',encoding='utf-8')
        (folder/'회신.txt').write_text('미회신 부서: 회계과',encoding='utf-8')
        pid=self.create();self.source(pid,folder);self.start()
        self.wait(pid,lambda v:v['jobs'][-1]['status']=='completed')
        with patch.object(config,'active_profile',return_value={'provider':'openai_compatible','_name':'local'}),patch.object(projects.local_ai,'local_profile',return_value={'model':'test','base_url':'http://127.0.0.1:11434/v1'}),patch.object(projects.folder_ai,'call_model',return_value=('{"refs":[1]}',{'actual_response':True})):
            self.question(pid,'교육 회신 마감과 미회신 부서는?')
            v=self.answered(pid)
            self.assertIn('11월 6일',v['messages'][-1]['content'])
            self.assertIn('회계과',v['messages'][-1]['content'])


if __name__=='__main__':
    unittest.main()
