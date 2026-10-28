"""Real HTTP questions with AI disabled, affiliation, paraphrases and categories."""
import json
import unittest
from unittest.mock import patch
import test_institution_rules as fixtures
from app import folders, guidance, knowledge, llm

RULE=fixtures.RULE
PROFILE=dict(confirmed=True,personnel_framework='national_public_official',organization=RULE['institution'],region='서울',department='총무과')

class InstitutionContextTest(unittest.TestCase):
    create=fixtures.InstitutionRulesApiTest.create
    apply=fixtures.InstitutionRulesApiTest.apply

    def setUp(self):
        fixtures.InstitutionRulesApiTest.setUp(self)
        for target,name,value in ((knowledge,'_experience_hits',[]),(guidance.store,'list_forms',[]),(guidance.manual_knowledge,'respond',None),
                                  (guidance.service_knowledge,'retrieve',dict(evidence=[],notice=''))):
            p=patch.object(target,name,return_value=value);p.start();self.addCleanup(p.stop)
        p=patch.object(llm,'get_provider',side_effect=AssertionError('AI-off must not construct a provider'));p.start();self.addCleanup(p.stop)

    def publish(self,**changes):return self.apply(self.create(**changes)).json()

    def ask(self,query,profile=PROFILE,**extra):
        response=self.client.post('/api/ask',json=dict(query=query,guidance=True,use_ai=False,today='2026-10-26',affiliation=profile,**extra))
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def education(self,**changes):
        return self.publish(title='연수 참가 접수 안내',keywords=['연수 신청 접수'],category='교육·행사',
            text='교육 희망자 회신 마감은 교육 시작 5일 전입니다.\n필요한 서식은 교육참가 신청서입니다.',**changes)

    def test_own_affiliation_paraphrase_returns_exact_quote_and_form_without_names(self):
        doc=self.education()
        form=self.publish(title='교육참가 신청서',kind='서식',keywords=['교육참가 신청서'],category='교육·행사',
            text='교육참가 신청서의 필수 항목은 부서, 성명, 연락처입니다.')
        for query in ('교육에 참여하려는데 언제까지 내야 해요?','연수 참석자 마감이 언제인가요?'):
            with self.subTest(query=query):
                reply=self.ask(query)
                self.assertIn('5일 전',reply['answer'])
                self.assertEqual({h['source_id'] for h in reply['knowledge']['evidence']},{doc['source_id']})
                self.assertEqual(reply['guidance']['institution_scope']['basis'],'affiliation')
                self.assertIn('내 소속 설정',reply['knowledge']['notice'])
                self.assertEqual([f['source_id'] for f in reply['guidance']['forms']],[form['source_id']])
                self.assertFalse(reply['guidance']['ai_used'])
                h=reply['knowledge']['evidence'][0]
                self.assertEqual(h['sha256'],doc['versions'][0]['sha256'])
                self.assertIn(h['quote'],doc['versions'][0]['text'])

    def test_no_profile_or_unconfirmed_profile_does_not_guess_agency(self):
        self.education()
        for profile in (None,dict(PROFILE,confirmed=False),dict(PROFILE,organization='존재하지 않는 기관'),dict(PROFILE,organization=['오류'])):
            reply=self.ask('교육에 참여하려는데 언제까지 내나요?',profile=profile)
            self.assertFalse(reply['knowledge']['evidence'])
            self.assertNotIn('5일 전',reply['answer'])

    def test_other_agencies_and_explicit_personnel_override_own_affiliation(self):
        own=self.education()
        other=self.education(institution='다른 검증시청')
        reply=self.ask('다른 검증시청 교육에 참여하려는데 언제까지 내나요?')
        self.assertEqual({h['source_id'] for h in reply['knowledge']['evidence']},{other['source_id']})
        self.assertNotIn('업무환경: 국가공무원',reply['query'])
        for query in ('없는시청 교육 마감은?','다른 기관 교육 마감은?','지방공무원 교육 마감은?'):
            reply=self.ask(query)
            self.assertNotIn(own['source_id'],{h['source_id'] for h in reply['knowledge']['evidence']})
            self.assertNotIn('업무환경: 국가공무원',reply['query'])

    def test_semantic_followup_uses_latest_task_but_new_topic_wins(self):
        doc=self.education()
        self.publish(title='교육참가 신청서',kind='서식',keywords=['교육참가 신청서'],category='교육·행사',
            text='교육참가 신청서의 필수 항목은 부서, 성명, 연락처입니다.')
        reply=self.ask('그럼 어떤 양식을 쓰면 돼요?',situation_context='교육에 참여하려는데 언제까지 내나요?')
        self.assertIn(doc['source_id'],{h['source_id'] for h in reply['knowledge']['evidence']})
        self.assertTrue(reply['guidance']['forms'])
        other=self.ask('사무용품을 구입할 예산 목은?',situation_context='교육에 참여하려는데 언제까지 내나요?')
        self.assertFalse(any(h.get('reference_kind')=='institution_rule' for h in other['knowledge']['evidence']))

    def test_followup_for_form_fields_does_not_inherit_old_deadline_requirement(self):
        self.education()
        form=self.publish(title='교육참가 신청서',kind='서식',keywords=['교육참가 신청서'],category='교육·행사',
            text='교육참가 신청서의 필수 항목은 부서, 성명, 연락처입니다.')
        reply=self.ask('그럼 어떤 항목을 적어야 하나요?',situation_context='교육에 참여하려는데 언제까지 내나요?\n그럼 어떤 양식을 쓰면 돼요?')
        self.assertEqual({h['source_id'] for h in reply['knowledge']['evidence']},{form['source_id']})
        self.assertIn('연락처',reply['answer'])
        self.assertEqual(reply['guidance']['context'],'그럼 어떤 항목을 적어야 하나요?')

    def test_uploaded_separate_lines_link_adjacent_form_in_same_applied_version(self):
        form=self.publish(title='교육참가 신청서',kind='서식',keywords=['교육참가 신청서'],text='교육참가 신청서의 필수 항목은 성명입니다.')
        raw='교육 희망자 회신 마감은 교육 시작 3일 전입니다.\n필요한 서식은 교육참가 신청서입니다.'
        response=self.client.post('/api/institution-rules/upload',data=dict(title='교육 회신 안내',institution=RULE['institution'],keywords='["연수 신청 접수"]',effective_date='2026-01-01'),files={'file':('안내.txt',raw.encode(),'text/plain')})
        self.assertEqual(response.status_code,201,response.text)
        doc=self.apply(response.json()).json()
        answer=self.ask('교육에 참여하려는데 언제까지 내야 해요?')
        self.assertEqual([h['loc'] for h in answer['knowledge']['evidence']],['1행 · v1'])
        self.assertEqual([f['source_id'] for f in answer['guidance']['forms']],[form['source_id']])
        # An unrelated later section is not scanned to invent a form link.
        later=raw.replace('\n필요한','\n다른 업무 안내입니다.\n필요한')
        newer=self.client.post('/api/institution-rules/'+doc['id']+'/versions',json={**RULE,'title':'교육 회신 안내','keywords':['연수 신청 접수'],'revision':doc['revision'],'text':later}).json()
        # Pending draft cannot supply a new context or replace the applied one.
        self.assertEqual([f['source_id'] for f in self.ask('교육 마감은?')['guidance']['forms']],[form['source_id']])
        later_upload=self.client.post('/api/institution-rules/upload',data=dict(title='교육 회신 안내',institution=RULE['institution'],keywords='["연수 신청 접수"]',effective_date='2026-01-01',rule_id=doc['id'],revision=str(newer['revision'])),files={'file':('안내.txt',(later+'\n끝.').encode(),'text/plain')})
        self.assertEqual(later_upload.status_code,201,later_upload.text)
        self.apply(later_upload.json())
        self.assertFalse(self.ask('교육 마감은?')['guidance']['forms'])

    def test_budget_question_does_not_expand_neighboring_inspection_form(self):
        self.publish(title='검수확인서',kind='서식',keywords=['검수확인서'],text='검수확인서입니다.')
        raw='사무용품 구매 예산 과목은 합성 일반수용비입니다.\n필요한 서식은 검수확인서입니다.'
        response=self.client.post('/api/institution-rules/upload',data=dict(title='물품 안내',institution=RULE['institution'],keywords='["사무용품"]',effective_date='2026-01-01'),files={'file':('안내.txt',raw.encode(),'text/plain')})
        self.assertEqual(response.status_code,201,response.text)
        self.apply(response.json())
        self.assertFalse(self.ask('사무용품을 무슨 목으로 구입하나요?')['guidance']['forms'])

    def test_budget_does_not_return_inspection_rule_with_broad_purchase_keyword(self):
        self.publish(title='물품 검수 지침',keywords=['물품'],category='물품·계약',text='납품을 받으면 검사하고 검사조서를 작성합니다.')
        reply=self.ask('사무용품을 사려는데 무슨 목으로 구입해야 하나요?')
        self.assertFalse(reply['knowledge']['evidence'])
        budget=self.publish(title='사무용품 예산 안내',keywords=['일반수용비 집행'],category='예산·회계',text='사무용품 구매 예산 과목은 합성 검증용 일반수용비입니다.')
        reply=self.ask('사무용품을 사려는데 무슨 목으로 구입해야 하나요?')
        self.assertEqual({h['source_id'] for h in reply['knowledge']['evidence']},{budget['source_id']})
        self.assertIn('합성 검증용 일반수용비',reply['answer'])

    def test_category_does_not_make_unrelated_content_answerable(self):
        self.education()
        for query in ('교육비 지급액은 얼마인가요?','등록되지 않은 수당 지급액이 궁금해요','교육 홍보물의 저작권 허용범위는?','교육 저작권은?',RULE['institution']+' 교육 저작권은?'):
            reply=self.ask(query)
            self.assertFalse(reply['knowledge']['evidence'],query)

    def test_parent_and_child_institution_names_never_share_explicit_scope(self):
        parent=self.education(institution='부산광역시')
        child=self.publish(title='교육 마감',institution='부산광역시교육청',keywords=['교육 마감'],category='교육·행사',text='교육 마감은 9일 전입니다.')
        profile=dict(PROFILE,organization='부산광역시')
        reply=self.ask('부산광역시교육청 교육 마감은?',profile=profile)
        self.assertEqual({h['source_id'] for h in reply['knowledge']['evidence']},{child['source_id']})
        self.assertIn('9일 전',reply['answer'])
        self.assertNotIn('5일 전',reply['answer'])
        reply=self.ask('부산광역시는 교육 마감이 언제예요?',profile=profile)
        self.assertEqual({h['source_id'] for h in reply['knowledge']['evidence']},{parent['source_id']})

    def test_unregistered_council_is_not_mistaken_for_parent_with_korean_particle(self):
        parent=self.education(institution='부산광역시')
        profile=dict(PROFILE,organization='부산광역시')
        reply=self.ask('부산광역시의회 교육 마감은?',profile=profile)
        self.assertFalse(reply['knowledge']['evidence'])
        reply=self.ask('부산광역시의 교육 마감은?',profile=profile)
        self.assertEqual({h['source_id'] for h in reply['knowledge']['evidence']},{parent['source_id']})

    def test_disabled_future_and_selected_library_remain_excluded(self):
        doc=self.education()
        reply=self.ask('연수 마감은?',knowledge_library_id='another-library')
        self.assertFalse(reply['knowledge']['evidence'])
        self.client.patch('/api/institution-rules/'+doc['id'],json=dict(operation='disable',revision=doc['revision']))
        self.assertFalse(self.ask('연수 마감은?')['knowledge']['evidence'])

    def test_categories_are_versioned_and_legacy_payloads_are_not_rewritten(self):
        doc=self.publish(category='교육·행사')
        before=doc['versions'][0]
        changed=self.client.post('/api/institution-rules/'+doc['id']+'/versions',json={**RULE,'category':'복무·휴가','revision':doc['revision']}).json()
        self.assertEqual(changed['category'],'교육·행사')
        comparison=self.client.get('/api/institution-rules/'+doc['id']+'/compare',params=dict(from_version=before['id'],to_version=changed['versions'][-1]['id'])).json()
        self.assertIn('category',{d['field'] for d in comparison['metadata_changes']})
        self.assertEqual(self.apply(changed).json()['category'],'복무·휴가')
        legacy=self.create()
        with folders.db() as c:
            v=legacy['versions'][0];v.pop('category')
            raw=json.dumps(v,ensure_ascii=False)
            c.execute('UPDATE institution_rule_versions SET payload=? WHERE id=?',(raw,v['id']))
        detail=self.client.get('/api/institution-rules/'+legacy['id']).json()
        self.assertEqual(detail['category'],'미분류')
        self.assertEqual(detail['versions'][0]['category'],'미분류')
        with folders.db() as c:self.assertEqual(c.execute('SELECT payload FROM institution_rule_versions WHERE id=?',(v['id'],)).fetchone()[0],raw)
        self.assertIn('예산·회계',self.client.get('/api/institution-rules').json()['categories'])
        rejected=self.client.post('/api/institution-rules',json={**RULE,'category':'없는분류'})
        self.assertEqual(rejected.status_code,422)

if __name__=='__main__':unittest.main()
