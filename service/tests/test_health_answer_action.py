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
            if row['article'] not in ('제19조(공가)', '제7조의6(공가)', '제20조(특별휴가)', '제7조의7(특별휴가)'):
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
