"""A reply to what the app just asked continues that question; a new question stays new."""
import json
from unittest.mock import patch
from test_core import Base, ROOT
from app import guidance, knowledge, llm, main


class EffectiveQueryTest(Base):
    def test_a_status_reply_continues_the_last_task(self):
        for context, reply in (('연가 며칠이야?', '국가공무원이에요'), ('병가 쓰려면 어떻게 해?', '소방공무원이에요'),
                               ('연가 며칠이야?', '지방직입니다'), ('병가 쓰려면?', '저는 경찰공무원입니다.'), ('연가 며칠이야?', '공무직이요')):
            with self.subTest(reply=reply):
                got = guidance.effective_query(reply, context)
                self.assertIn(context, got)
                self.assertIn(reply, got)

    def test_only_the_latest_status_counts(self):
        got = guidance.effective_query('국가공무원이에요', '지방직인데 연가 며칠이야?')
        self.assertIn('국가공무원', got)
        self.assertNotIn('지방직', got)
        got = guidance.effective_query('국가공무원이에요', '연가 며칠이야?\n지방직이에요')
        self.assertNotIn('지방직', got)

    def test_a_reply_to_the_question_asked_back_continues_it(self):
        for context, reply in (('휴가 쓰려고 하는데 어떤 걸로 해야 하나요?', '아이가 아파서요'),
                               ('출장 여비 알려줘', '2026-10-20부터 2026-10-22까지요'), ('물품 구매하려고 해요', '납품 검사요')):
            with self.subTest(reply=reply):
                got = guidance.effective_query(reply, context)
                self.assertIn(context, got)
                self.assertIn(reply, got)

    def test_a_reply_that_is_complete_by_itself_drops_the_vague_opening(self):
        self.assertEqual(guidance.effective_query('초임호봉 획정이요', '호봉 알려줘'), '초임호봉 획정이요')
        self.assertEqual(guidance.effective_query('초임호봉 획정이요', '지방직 호봉 알려줘'), '지방직 초임호봉 획정이요')

    def test_a_question_without_its_own_subject_stays_on_the_task(self):
        self.assertIn('병가', guidance.effective_query('진단서는 언제 내요?', '병가 쓰려면 어떻게 해?\n소방공무원이에요'))
        got = guidance.effective_query('서식도 알려줘', '출장 여비 알려줘\n정산 기한이요')
        self.assertIn('출장 여비', got)
        self.assertIn('정산 기한이요', got)
        self.assertEqual(guidance.effective_query('진단서는 언제 내요?', ''), '진단서는 언제 내요?')

    def test_a_what_if_question_stays_on_the_task(self):
        self.assertIn('건강검진', guidance.effective_query('같은 날 못 받으면요?', '소방공무원 건강검진'))
        self.assertEqual(guidance.effective_query('회의실은요?', '연가 며칠이야?'), '회의실은요?')

    def test_own_illness_reply_reaches_sick_leave(self):
        self.assertEqual(knowledge.intent.analyze(guidance.effective_query('제가 독감이에요', '휴가 쓰려고 하는데 어떤 걸로 해야 하나요?'))['topics'], ['sick'])

    def test_finance_status_reply_accepts_a_spoken_ending(self):
        self.assertIn('예산 과목', guidance.effective_query('지방자치단체요', '사무용품 예산 과목 알려줘'))

    def test_the_contract_party_reply_is_stated_as_the_party(self):
        got = guidance.effective_query('지방자치단체요', '소방공무원 물품 구매 검수 절차')
        self.assertIn('소방공무원 물품 구매 검수 절차', got)
        self.assertIn('계약당사자는 지방자치단체입니다', got)

    def test_a_short_elliptical_question_keeps_the_stated_status(self):
        self.assertIn('소방공무원', guidance.effective_query('병가는요?', '소방공무원인데 연가 며칠이야?'))
        self.assertIn('국가공무원', guidance.effective_query('병가는요?', '연가 며칠이야?\n국가공무원이에요'))
        self.assertNotIn('연가', guidance.effective_query('병가는요?', '연가 며칠이야?\n국가공무원이에요'))
        self.assertEqual(guidance.effective_query('병가는요?', '연가 며칠이야?'), '병가는요?')
        self.assertEqual(guidance.effective_query('지방직 병가는요?', '국가공무원인데 연가 며칠이야?'), '지방직 병가는요?')

    def test_a_new_question_stays_new(self):
        for context, query in (('연가 며칠이야?', '출장 정산 언제까지 해요?'), ('연가 며칠이야?', '공문 어떻게 써요?'), ('병가 쓰려면?', '공가를 쓰려면?'),
                               ('출장 다녀왔어', '등록 안 된 수당 기한을 알려줘'), ('연가 며칠이야?', '점심시간은 몇 시예요?'), ('연가 며칠이야?', '교육 희망자 취합은 어떻게 해요?'),
                               ('휴가 쓰려고 하는데 어떤 걸로 해야 하나요?', '출장 정산 기한'), ('호봉 알려줘', '연가 며칠이야?')):
            with self.subTest(query=query):
                self.assertEqual(guidance.effective_query(query, context), query)

    def test_small_talk_is_not_a_reply(self):
        for query in ('네', '감사합니다', '고마워요', '알겠어요', '아니요', '좋아요'):
            with self.subTest(query=query):
                self.assertEqual(guidance.effective_query(query, '연가 며칠이야?'), query)

    def test_no_task_in_context_keeps_the_reply_alone(self):
        self.assertEqual(guidance.effective_query('국가공무원이에요', ''), '국가공무원이에요')
        self.assertEqual(guidance.effective_query('국가공무원이에요', '안녕하세요'), '국가공무원이에요')


class FollowUpAnswerTest(Base):
    def setUp(self):
        knowledge.initialize()
        root = ROOT / 'reference_data/official-20261020'
        rows = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
        self.sources = []
        for row in rows:
            if row['article'] not in ('제18조(병가)', '제7조의5(병가)', '제15조(연가 일수)', '제7조(연가일수 및 연가보상비의 지급)', '제20조(특별휴가)', '제7조의7(특별휴가)', '제17조(검사)', '제64조(검사)'):
                continue
            text = (root / 'excerpts' / row['filename']).read_text(encoding='utf-8')
            self.sources.append(dict(id=row['sha256'][:20], title=row['title']+' '+row['article'],
                enabled=True, current=True, sha256=row['sha256'], effective_date=row['effective_date'],
                kind=row['kind'], institution=row['institution'], limited=False, library_id='public',
                file_id=row['sha256'][:20], units=[dict(text=text, loc='보관 본문')], official=row))

    def ask(self, query, context):
        with patch.object(knowledge, 'sources', return_value=self.sources), patch.object(llm, 'get_provider', side_effect=AssertionError('AI must stay off')):
            return main.api_ask(dict(query=query, situation_context=context, guidance=True, use_ai=False, today='2026-11-07'))

    def titles(self, result):
        return ' '.join(e['title'] for e in result['knowledge']['evidence'])

    def test_status_replies_get_that_status_rule(self):
        self.assertIn('제15조', self.titles(self.ask('국가공무원이에요', '연가 며칠이야?')))
        self.assertIn('제18조', self.titles(self.ask('소방공무원이에요', '병가 쓰려면 어떻게 해?')))
        self.assertIn('제7조의5', self.titles(self.ask('지방직입니다', '병가 쓰려면 어떻게 해?')))

    def test_family_illness_reply_reaches_family_care(self):
        result = self.ask('아이가 아파서요', '휴가 쓰려고 하는데 어떤 걸로 해야 하나요?')
        self.assertEqual(result['knowledge']['tree']['rule_id'], 'family-care-situation')

    def test_contract_party_reply_reaches_the_contract_law(self):
        result = self.ask('지방자치단체요', '소방공무원 물품 구매 검수 절차')
        self.assertIn('지방자치단체를 당사자로 하는 계약', self.titles(result))
        self.assertEqual(result['knowledge']['tree']['rule_id'], 'goods-inspection')

    def test_national_party_reply_is_not_asked_again(self):
        result = self.ask('국가기관이요', '소방공무원 물품 구매 검수 절차')
        self.assertNotIn('계약당사자가 지방자치단체(시·도)인지', result.get('notice') or '')
        self.assertNotIn('지방자치단체를 당사자로 하는 계약', self.titles(result))
        self.assertIn('국가를 당사자로 하는 계약', json.dumps(result['knowledge']['tree'], ensure_ascii=False))

    def test_a_task_detail_question_gets_the_task_answer(self):
        result = self.ask('진단서는 언제 내요?', '병가 쓰려면 어떻게 해?\n소방공무원이에요')
        self.assertIn('제18조', self.titles(result))
        self.assertIn('진단서', json.dumps(result['knowledge']['tree'], ensure_ascii=False))
