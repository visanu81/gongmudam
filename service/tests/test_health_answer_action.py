"""Health-check answers give an action without implying every check qualifies."""
import copy
import json
from unittest.mock import patch
from test_core import Base, ROOT
from app import answer_tree, knowledge, llm, main


class HealthAnswerActionTest(Base):
    def setUp(self):
        knowledge.initialize()
        root = ROOT / 'reference_data/official-20261020'
        rows = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
        self.sources = []
        for row in rows:
            if row['article'] not in ('제19조(공가)', '제7조의6(공가)', '제20조(특별휴가)', '제7조의7(특별휴가)', '제18조(병가)', '제7조의5(병가)'):
                continue
            text = (root / 'excerpts' / row['filename']).read_text(encoding='utf-8')
            self.sources.append(dict(id=row['sha256'][:20], title=row['title']+' '+row['article'],
                enabled=True, current=True, sha256=row['sha256'], effective_date=row['effective_date'],
                kind=row['kind'], institution=row['institution'], limited=False, library_id='public',
                file_id=row['sha256'][:20], units=[dict(text=text, loc='보관 본문')], official=row))

    def ask(self, query):
        with patch.object(knowledge, 'sources', return_value=self.sources), patch.object(llm, 'get_provider', side_effect=AssertionError('AI must stay off')):
            return main.api_ask(dict(query=query, guidance=True, use_ai=False, today='2026-10-26'))

    def test_requested_question_has_action_first_with_scope_and_time(self):
        question = '근무일에 건강검진 다녀와야하는데 복무처리는 어떤걸로 상신해야할까'
        for prefix, article in [('', '제7조의6('), ('국가공무원인데 ', '제19조('), ('지방공무원인데 ', '제7조의6(')]:
            with self.subTest(scope=prefix):
                result = self.ask(prefix+question)
                reply = result['knowledge']; tree = reply['tree']
                self.assertIn('공가’로 상신', tree['title'])
                self.assertIn('법정 건강검진이라면', tree['title'])
                self.assertIn('복무 종류는 공가', tree['branches'][0]['items'][0]['text'])
                self.assertTrue(any(e['official']['article'].startswith(article) for e in reply['evidence']))
                self.assertTrue(result['guidance']['deadlines'])
                self.assertFalse(result['guidance']['ai_used'])
                for branch in tree['branches']:
                    for item in branch['items']:
                        self.assertTrue(all(q in reply['evidence'][item['ref']-1]['quote'] for q in item['support_quotes']))

    def test_personal_check_keeps_eligibility_condition(self):
        for scope in ('국가공무원', '지방공무원'):
            result = self.ask(scope+' 개인적으로 예약한 종합 건강검진도 공가로 하루 쓸 수 있나요?')
            tree = result['knowledge']['tree']
            self.assertIn('법정 건강검진이라면', tree['title'])
            text = ' '.join(i['text'] for b in tree['branches'] for i in b['items'])
            self.assertIn('별도 확인', text)
            self.assertIn('하루 전체가 자동', text)

    def test_practice_excerpt_is_the_official_leave_section(self):
        for query in ('근무일에 건강검진 다녀와야하는데 복무처리는 어떤걸로 상신해야할까', '건강검진',
                      '국가공무원인데 근무일에 건강검진 다녀와야 해요'):
            with self.subTest(query=query):
                practice = self.ask(query)['guidance']['practice']
                self.assertEqual(len(practice), 1)
                self.assertIn('다. 공 가', practice[0]['loc'])
                self.assertIn('확진검사는 공가 대상이 아님', practice[0]['text'])
                self.assertNotIn('토요민원상황실', practice[0]['text'])

    def test_fire_officer_is_answered_from_the_fire_decree(self):
        for query in ('소방공무원인데 근무일에 건강검진 다녀와야 해요', '소방 건강검진', '소방공무원 건강검진 복무처리',
                      '소방공무원 건강검진은 어떤 복무로 신청하나요?', '소방서 근무자 건강진단 받으러 가요'):
            with self.subTest(query=query):
                result = self.ask(query)
                reply = result['knowledge']; tree = reply['tree']
                self.assertEqual(tree['rule_id'], 'service-rules:fire-health-leave')
                self.assertEqual(tree['title'], '법정 건강검진이라면 ‘공가’로 상신하세요.')
                self.assertEqual([b['label'] for b in tree['branches']], ['신청할 복무', '사용 기간·시간', '신청 전 확인'])
                self.assertEqual(reply['evidence'][tree['branches'][0]['items'][0]['ref']-1]['official']['article'], '제8조의2(공가)')
                text = ' '.join(i['text'] for b in tree['branches'] for i in b['items'])
                for needed in ('국민건강보험법', '특수·정밀건강진단', '119구조', '같은 날', '별도 확인'):
                    self.assertIn(needed, text)
                self.assertIn('같은 날', ' '.join(d['text'] for d in result['guidance']['deadlines']))
                self.assertFalse(result['guidance']['ai_used'])

    def test_other_fire_leave_questions_keep_the_general_answer(self):
        for query in ('소방공무원 공가 사유', '소방공무원인데 헌혈 다녀와야 해요', '소방공무원 배우자 건강검진',
                      '소방공무원 건강검진 비용 내고 다녀왔는데 공가 되나요'):
            with self.subTest(query=query):
                self.assertEqual(self.ask(query)['knowledge']['tree']['rule_id'], 'service-rules:fire-public-leave')

    def test_police_and_national_keep_the_national_decree(self):
        for query in ('경찰공무원인데 근무일에 건강검진 다녀와야 해요', '국가공무원인데 근무일에 건강검진 다녀와야 해요'):
            with self.subTest(query=query):
                reply = self.ask(query)['knowledge']
                self.assertEqual(reply['tree']['rule_id'], 'service-v70-public_health')
                self.assertTrue(reply['evidence'][0]['official']['article'].startswith('제19조('))

    def test_work_about_a_health_check_is_not_a_leave_answer(self):
        for query in ('건강검진 예산 품의', '건강검진 업체 계약', '직원 건강검진 예산 집행', '채용 건강진단서 비용', '신규 임용 건강진단서',
                      '공무원 건강검진 비용 지원', '건강검진 결과 제출해야 하나요', '건강검진비 지출 품의', '건강검진 대행기관 선정',
                      '건강검진 대상자 명단 정리', '지방공무원 건강검진 예산', '국가공무원 건강검진 비용 지원', '경찰 건강검진 예산',
                      '소방공무원 건강검진 비용 지원', '소방공무원 건강검진 결과 제출', '직원 건강검진 비용은 어떤 예산으로 집행하나요',
                      '건강검진 구매', '건강검진 결과 치료비 지원', '건강검진 결과 입원비 예산'):
            with self.subTest(query=query):
                result = self.ask(query)
                reply = result['knowledge']; tree = reply['tree']
                self.assertEqual(tree['title'], '건강검진 업무 자료가 필요해요')
                self.assertFalse(reply['evidence'])
                self.assertNotEqual(result['guidance']['topic'], 'leave')
                text = ' '.join(i['text'] for b in tree['branches'] for i in b['items'])
                self.assertIn('예산·계약·비용', text)
                self.assertIn('‘건강검진 공가’', text)
                self.assertFalse(result['guidance']['ai_used'])

    def test_health_check_contract_keeps_the_contract_topic(self):
        self.assertEqual(knowledge.intent.analyze('건강검진 수의계약')['topics'], ['goods_private_contract'])

    def test_leave_questions_with_the_same_words_keep_the_answer(self):
        for query in ('건강검진', '건강검진 받으려면', '건강검진 비용 내고 다녀왔는데 공가 되나요', '건강검진 다녀오면 결과지 제출해야 하나요',
                      '건강검진 진단서 제출해야 공가 되나요', '건강검진 결과 나왔는데 재검사도 공가인가요',
                      '국가공무원 건강검진은 어떤 복무로 신청하나요?', '근무일에 건강검진 다녀와야하는데 복무처리는 어떤걸로 상신해야할까'):
            with self.subTest(query=query):
                result = self.ask(query)
                self.assertIn('공가’로 상신', result['knowledge']['tree']['title'])
                self.assertEqual(result['guidance']['topic'], 'leave')

    def test_illness_found_by_a_check_is_answered_as_sick_leave(self):
        for prefix, article in (('', '제7조의5('), ('국가공무원 ', '제18조('), ('지방공무원 ', '제7조의5('), ('소방공무원 ', '제18조('), ('경찰공무원 ', '제18조(')):
            for question in ('건강검진 결과로 병가 쓸 수 있나요', '건강검진 결과 이상 있어서 쉬어야 해요', '건강검진 결과 치료받아야 해요',
                             '건강검진 이상 소견으로 입원해요', '건강검진에서 암 발견돼서 수술해요'):
                with self.subTest(query=prefix+question):
                    result = self.ask(prefix+question)
                    reply = result['knowledge']
                    self.assertEqual(reply['intent']['topics'], ['sick'])
                    self.assertIn('병가', reply['tree']['title'])
                    self.assertNotIn('공가', reply['tree']['title'])
                    self.assertEqual(result['guidance']['topic'], 'leave')
                    self.assertTrue(reply['evidence'][0]['official']['article'].startswith(article), reply['evidence'][0]['title'])
                    if prefix != '지방공무원 ':
                        self.assertIn('병', result['guidance']['practice'][0]['loc'])
                        self.assertNotIn('공 가', result['guidance']['practice'][0]['loc'])

    def test_a_check_as_the_purpose_keeps_the_official_leave_answer(self):
        for query in ('건강검진 받으러 병가 써도 되나요', '건강검진을 병가로 처리해도 되나요', '건강검진 때문에 병가 써야 하나요',
                      '건강검진은 병가인가요 공가인가요', '건강검진 결과 때문에 공가 쓸 수 있나요'):
            with self.subTest(query=query):
                self.assertIn('공가’로 상신', self.ask(query)['knowledge']['tree']['title'])

    def test_family_illness_is_not_own_sick_leave(self):
        self.assertNotEqual((knowledge.intent.analyze('지방공무원 부모 건강검진 결과 입원해요') or {}).get('topics'), ['sick'])

    def test_child_check_is_not_own_health_check(self):
        result = self.ask('지방공무원이 아이 건강검진에 동행할 때 공가인가요?')
        self.assertNotIn(result['knowledge']['tree'].get('rule_id'), ('health-leave', 'service-v70-public_health'))

    def test_missing_or_changed_authority_does_not_assert_entitlement(self):
        result = self.ask('국가공무원 건강검진은 어떤 복무로 신청하나요?')
        reply = copy.deepcopy(result['knowledge'])
        for hit in reply['evidence']:
            hit['sha256'] = '0'*64
        self.assertNotEqual(answer_tree.build(result['query'], reply)['kind'], 'summary')
        self.sources = []
        # Neither a registered nor a bundled national article is available.
        with patch.object(knowledge.service_rules, 'catalog', return_value=()):
            missing = self.ask('국가공무원 건강검진은 어떤 복무로 신청하나요?')
        self.assertFalse(missing['knowledge']['evidence'])
        self.assertNotIn('공가’로 상신', missing['knowledge']['tree']['title'])
