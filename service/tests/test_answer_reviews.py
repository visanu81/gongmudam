"""Reviewed answers: immutable drafts, explicit publication and source/scope guards."""
from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import answer_reviews as reviews, folders, institution_rules, knowledge, main, llm


class AnswerReviewTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.patch = patch.object(folders, 'DB_PATH', Path(temp.name)/'folders.db')
        self.patch.start(); self.addCleanup(self.patch.stop)
        env = patch.dict('os.environ', {'GONGMUDAM_PUBLIC':'0'})
        env.start(); self.addCleanup(env.stop)
        institution_rules.initialize()
        self.client = TestClient(main.app)  # No lifespan: never initialize live business stores.
        self.addCleanup(self.client.close)
        self.query = '합성 검증기관 교육자료 제출 기한은?'
        self.context = dict(query=self.query, affiliation=None, library_id=None, institution_rule_id=None, today='2026-10-26')
        r=self.client.post('/api/institution-rules',json=dict(title='교육자료 제출 안내',institution='합성 검증기관',kind='기관 지침',keywords=['교육자료 제출'],text='교육자료 제출기한은 3일 전입니다.',effective_date='2026-01-01',scope_notes='',change_note='합성 검증'))
        self.assertEqual(r.status_code,201,r.text)
        self.rule=r.json(); v=self.rule['versions'][0]
        r=self.client.patch('/api/institution-rules/'+self.rule['id'],json=dict(revision=self.rule['revision'],operation='apply',version_id=v['id'],reviewed_sha256=v['sha256']))
        self.assertEqual(r.status_code,200,r.text)
        self.rule=r.json()
        source=next(s for s in knowledge.sources() if s['id']==self.rule['source_id'])
        self.ref=dict(source_id=source['id'],sha256=source['sha256'],unit_index=0,quote=source['units'][0]['text'])

    def create(self, **changes):
        r=self.client.post('/api/answer-reviews',json=dict(context=self.context,rating='wrong',original_answer='기존 합성 답변',**changes))
        self.assertEqual(r.status_code,201,r.text)
        return r.json()

    def draft(self, d, **changes):
        body=dict(revision=d['revision'],answer='교육자료는 교육 3일 전까지 제출하세요.',reviewer='합성 검토자',valid_from='2026-10-26',evidence=[self.ref],alternate_questions=['합성 검증기관 교육자료 마감은 언제인가요?'])
        body.update(changes)
        return self.client.post('/api/answer-reviews/'+d['id']+'/versions',json=body)

    def apply(self,d,**changes):
        v=d['versions'][-1]
        body=dict(revision=d['revision'],operation='apply',version_id=v['id'],reviewed_sha256=v['sha256'],confirmed=True)
        body.update(changes)
        return self.client.patch('/api/answer-reviews/'+d['id'],json=body)

    def published(self,**changes):
        d=self.create();r=self.draft(d,**changes)
        self.assertEqual(r.status_code,201,r.text)
        r=self.apply(r.json());self.assertEqual(r.status_code,200,r.text)
        return r.json()

    def lookup(self,q=None,body=None,day='2026-10-26'):
        return reviews.lookup(q or self.query,body or {},date.fromisoformat(day))

    def test_feedback_draft_apply_offline_and_restart(self):
        d=self.create()
        self.assertIsNone(self.lookup())
        r=self.draft(d);self.assertEqual(r.status_code,201,r.text);d=r.json()
        self.assertIsNone(self.lookup())
        self.assertEqual(self.apply(d,confirmed=False).status_code,422)
        self.assertEqual(self.apply(d,reviewed_sha256='wrong').status_code,422)
        d=self.apply(d).json()
        with patch.object(llm,'get_provider',side_effect=AssertionError('AI must not run')):
            for ai in (False,True):
                response=self.client.post('/api/ask',json=dict(query=self.query,guidance=True,use_ai=ai,today='2026-10-26'))
                self.assertEqual(response.status_code,200,response.text)
                reply=response.json();self.assertEqual(reply['answer'],d['versions'][0]['answer'])
                self.assertEqual(reply['knowledge']['evidence'][0]['quote'],self.ref['quote'])
                self.assertEqual(reply['knowledge']['evidence'][0]['sha256'],self.ref['sha256'])
                self.assertIsNone(reply['model'])
        # Each request opens a new SQLite connection; a new client reloads persisted state.
        self.client.close()
        self.client=TestClient(main.app)
        self.addCleanup(self.client.close)
        self.assertEqual(self.client.get('/api/answer-reviews/'+d['id']).json()['active_version_id'],d['active_version_id'])
        self.assertEqual(self.lookup('합성 검증기관 교육자료 마감은 언제인가요?')['response']['answer'],reply['answer'])
        self.assertIsNone(self.lookup('합성 검증기관 교육자료 출장 기한은?'))

    def test_source_changed_or_disabled_never_serves_reviewed_answer(self):
        d=self.published()
        with patch.object(reviews,'source_map',return_value={}):
            self.assertIsNone(self.lookup()['response'])
            self.assertEqual(self.client.get('/api/answer-reviews/'+d['id']).json()['state'],'needs_review')
        r=self.client.patch('/api/institution-rules/'+self.rule['id'],json={'revision':self.rule['revision'],'operation':'disable'})
        self.assertEqual(r.status_code,200,r.text)
        self.assertIsNone(self.lookup()['response'])

    def test_source_hash_quote_and_unit_validation(self):
        d=self.create()
        for ref in (self.ref|{'quote':'원문에 없는 내용'},self.ref|{'sha256':'0'*64},self.ref|{'unit_index':999},self.ref|{'source_id':'missing'}):
            with self.subTest(ref=ref):self.assertEqual(self.draft(d,evidence=[ref]).status_code,422)
        self.assertEqual(self.draft(d,evidence=[]).status_code,422)
        self.assertEqual(self.draft(d,evidence=[self.ref,self.ref]).status_code,422)

    def test_date_scope_and_foreign_alias_guards(self):
        d=self.published(valid_until='2026-10-27')
        self.assertIsNone(self.lookup(day='2026-10-25'))
        self.assertIsNone(self.lookup(day='2026-10-28'))
        self.assertIsNone(self.lookup(body={'knowledge_library_id':'other'}))
        self.assertIsNone(self.lookup(body={'affiliation':dict(confirmed=True,personnel_framework='national_public_official',organization='다른 검증기관')}))
        d=self.draft(d,alternate_questions=['다른 기관 교육자료 제출 기한은?']).json()
        self.assertEqual(self.apply(d).status_code,422)

    def test_revisions_immutable_history_and_disable(self):
        d=self.published();original=d['versions'][0].copy()
        self.assertEqual(self.draft(d,revision=1).status_code,409)
        r=self.draft(d,answer='개정 검토 초안');self.assertEqual(r.status_code,201,r.text);d=r.json()
        self.assertEqual(d['versions'][0],original)
        self.assertEqual(d['original_answer'],'기존 합성 답변')
        self.assertEqual(self.lookup()['response']['answer'],original['answer'])
        self.assertEqual(self.apply(d,version_id=original['id'],reviewed_sha256=original['sha256']).status_code,422)
        r=self.client.patch('/api/answer-reviews/'+d['id'],json=dict(revision=d['revision'],operation='disable'))
        self.assertEqual(r.status_code,200,r.text)
        self.assertIsNone(self.lookup())
        self.assertEqual(len(r.json()['versions']),2)
        self.assertEqual(len(r.json()['history']),5)

    def test_conflicting_published_question_blocked(self):
        self.published()
        d=self.draft(self.create()).json()
        self.assertEqual(self.apply(d).status_code,409)

    def test_feedback_all_ratings_and_resolve(self):
        d=self.create()
        for rating in ('solved','insufficient','wrong'):
            r=self.client.patch('/api/answer-reviews/'+d['id']+'/feedback',json=dict(revision=d['revision'],rating=rating,note='점검'))
            self.assertEqual(r.status_code,200,r.text);d=r.json();self.assertEqual(d['rating'],rating)
        d=self.client.patch('/api/answer-reviews/'+d['id'],json=dict(revision=d['revision'],operation='resolve')).json()
        self.assertEqual(d['state'],'resolved')
        d=self.client.patch('/api/answer-reviews/'+d['id'],json=dict(revision=d['revision'],operation='reopen')).json()
        self.assertEqual(d['state'],'pending')

    def test_public_and_origin_mutations_blocked(self):
        d=self.published()
        with patch.dict('os.environ',{'GONGMUDAM_PUBLIC':'1'}):
            self.assertIsNone(self.lookup())
            self.assertEqual(self.draft(d).status_code,403)
            self.assertTrue(self.client.get('/api/answer-reviews').json()['public_read_only'])
        self.assertIsNone(reviews.lookup(self.query,{},date(2026,10,26),public_mode=True))
        r=self.client.patch('/api/answer-reviews/'+d['id'],json=dict(revision=d['revision'],operation='disable'),headers={'Origin':'https://other.example'})
        self.assertEqual(r.status_code,403)

    def test_candidates_return_exact_registered_units(self):
        d=self.create()
        r=self.client.get('/api/answer-reviews/sources',params=dict(review_id=d['id'],query='교육자료 제출'))
        self.assertEqual(r.status_code,200,r.text)
        hit=next(s for s in r.json()['items'] if s['source_id']==self.ref['source_id'])
        self.assertEqual(hit['text'],self.ref['quote'])
        self.assertEqual(hit['unit_index'],0)

    def test_changed_original_hash_does_not_use_previous_answer(self):
        self.published()
        universe=reviews.source_map()
        universe[self.ref['source_id']]['sha256']='b'*64
        with patch.object(reviews,'source_map',return_value=universe):
            result=self.lookup()
            self.assertIsNone(result['response'])
            self.assertIn('원문이 바뀌',result['issues'][0])

    def test_unknown_source_date_and_future_question_not_applied(self):
        d=self.create()
        d=self.draft(d,alternate_questions=['합성 검증기관 2027년 교육자료 제출 기한은?']).json()
        self.assertEqual(self.apply(d).status_code,422)

    def test_same_profile_is_required_for_affiliation_scoped_answer(self):
        profile=dict(confirmed=True,personnel_framework='national_public_official',organization='합성 검증기관',department='총무과',region='서울')
        from app import institution_matching
        query=institution_matching.scope_query(self.query,profile)
        self.context.update(query=query,affiliation=profile)
        d=self.published()
        r=self.client.post('/api/ask',json=dict(query=self.query,affiliation=profile,guidance=True,use_ai=False,today='2026-10-26'))
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['reviewed_answer']['review_id'],d['id'])
        self.assertIsNone(self.lookup(q=query))
        self.assertIsNone(self.lookup(q=query,body={'affiliation':profile|{'department':'다른 부서'}}))

    def test_reopen_stops_applied_answer_and_resolved_draft_leaves_open_queue(self):
        d=self.published()
        r=self.client.patch('/api/answer-reviews/'+d['id'],json=dict(revision=d['revision'],operation='reopen'))
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['state'],'pending')
        self.assertIsNone(self.lookup())
        other=self.draft(self.create()).json()
        other=self.client.patch('/api/answer-reviews/'+other['id'],json=dict(revision=other['revision'],operation='resolve')).json()
        self.assertEqual(other['state'],'resolved')


if __name__=='__main__': unittest.main()
