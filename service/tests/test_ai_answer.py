import json
import unittest
from unittest import mock

from app import ai_answer

ITEMS = [
    dict(id='a:0:0', source_id='a', title='지방공무원 복무규정 제7조의5(병가)', loc='제7조의5', text=(
        '제7조의5(병가) ① 지방자치단체의 장과 지방의회의 의장은 소속 공무원이 다음 각 호의 어느 하나에 해당할 경우에는 '
        '연 60일의 범위에서 병가를 허가할 수 있다.\n② 공무상 부상등으로 직무를 수행할 수 없거나 요양이 필요할 경우에는 '
        '연 180일의 범위에서 병가를 허가할 수 있다.\n④ 병가 일수가 연 6일을 초과하는 경우에는 의사의 진단서를 첨부해야 한다.')),
    dict(id='b:0:0', source_id='b', title='공무원 여비 규정 제8조의2', loc='제8조의2', text=(
        '② 국내 여행자 및 국외 여행자는 여행을 마친 날의 다음 날부터 기산(起算)하여 2주일 이내에 정산을 신청하여야 한다.')),
]


def answer(**kw):
    base = dict(can_answer=True, conclusion='일반 병가는 연 60일이에요.', conclusion_refs=['S1'],
                conclusion_quote='연 60일의 범위에서 병가를 허가할 수 있다', points=[], missing=[])
    return base | kw


class QuoteCheck(unittest.TestCase):
    def test_conclusion_needs_a_quote_found_in_its_source(self):
        self.assertIsNotNone(ai_answer.validate(answer(), ITEMS))
        self.assertIsNone(ai_answer.validate(answer(conclusion_quote='연 90일의 범위에서 병가를 허가'), ITEMS))
        # The right words in the wrong source do not count.
        self.assertIsNone(ai_answer.validate(answer(conclusion_refs=['S2']), ITEMS))
        self.assertIsNone(ai_answer.validate(answer(conclusion_refs=['S9']), ITEMS))
        self.assertIsNone(ai_answer.validate(answer(conclusion_quote='병가'), ITEMS))

    def test_joined_spans_are_each_checked(self):
        joined = '「연 60일의 범위에서 병가를 허가할 수 있다.」, 「연 180일의 범위에서 병가를 허가할 수 있다.」'
        self.assertIsNotNone(ai_answer.validate(answer(conclusion_quote=joined), ITEMS))
        bad = '「연 60일의 범위에서 병가를 허가할 수 있다.」, 「연 365일의 범위에서 병가를 허가할 수 있다.」'
        self.assertIsNone(ai_answer.validate(answer(conclusion_quote=bad), ITEMS))

    def test_unsupported_points_are_dropped_and_counted(self):
        points = [dict(kind='절차', text='6일을 넘으면 진단서를 내요.', refs=['S1'], quote='의사의 진단서를 첨부해야 한다'),
                  dict(kind='예외', text='지어낸 예외예요.', refs=['S1'], quote='국무총리가 정하는 경우에는 예외로 한다')]
        result = ai_answer.validate(answer(points=points), ITEMS)
        self.assertEqual([p['kind'] for p in result['points']], ['절차'])
        self.assertEqual(result['dropped'], 1)

    def test_internal_ids_and_unchecked_specifics_are_removed(self):
        result = ai_answer.validate(answer(conclusion='일반 병가는 연 60일이에요(S1, S2).',
                                           missing=['소속이 국가공무원인가요?', '국가공무원 복무규정 제10조를 확인했나요?', '30일을 썼나요?']), ITEMS)
        self.assertEqual(result['conclusion'], '일반 병가는 연 60일이에요.')
        self.assertEqual(result['missing'], ['소속이 국가공무원인가요?'])

    def test_cannot_answer_keeps_only_questions(self):
        result = ai_answer.validate(dict(can_answer=False, missing=['어느 기관 소속인가요?']), ITEMS)
        self.assertEqual(result, {'can_answer': False, 'missing': ['어느 기관 소속인가요?']})


class FakeProvider:
    available = True

    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def chat(self, messages, **kw):
        self.calls.append((messages, kw))
        return json.dumps(self.reply, ensure_ascii=False)


class Compose(unittest.TestCase):
    def run_compose(self, reply):
        provider = FakeProvider(reply)
        with mock.patch.object(ai_answer, 'provider_for_answer', return_value=(provider, {'model': 'solar-pro4'})), \
             mock.patch.object(ai_answer, 'passages', return_value=ITEMS):
            out = ai_answer.compose('지방공무원 병가 며칠?', {'hits': []}, {'mode': 'source_search', 'evidence': []})
        return out, provider

    def test_supported_answer_becomes_the_tree_with_numbered_evidence(self):
        points = [dict(kind='기한', text='정산은 2주일 안에 신청해요.', refs=['S2'], quote='2주일 이내에 정산을 신청하여야 한다')]
        out, provider = self.run_compose(answer(points=points))
        self.assertEqual(out['mode'], 'ai_answer')
        self.assertEqual(out['tree']['title'], '일반 병가는 연 60일이에요.')
        self.assertEqual([e['title'] for e in out['evidence']], [ITEMS[0]['title'], ITEMS[1]['title']])
        self.assertEqual([i['ref'] for b in out['tree']['branches'] for i in b['items']], [1, 2])
        # The model is told to use only the sources and receives them as data.
        messages, kw = provider.calls[0]
        self.assertIn('등록 원문만 근거로', messages[0]['content'])
        self.assertEqual(kw['response_schema'], ai_answer.SCHEMA)
        self.assertIn('S2', messages[1]['content'])

    def test_unsupported_conclusion_keeps_the_rule_answer(self):
        out, _ = self.run_compose(answer(conclusion_quote='연 99일의 범위에서 병가를 허가할 수 있다'))
        self.assertIsNone(out)

    def test_model_error_keeps_the_rule_answer(self):
        class Broken(FakeProvider):
            def chat(self, messages, **kw):
                raise ai_answer.llm.LLMError('모델 서버 연결 실패')
        with mock.patch.object(ai_answer, 'provider_for_answer', return_value=(Broken({}), {'model': 'x'})), \
             mock.patch.object(ai_answer, 'passages', return_value=ITEMS):
            self.assertIsNone(ai_answer.compose('질문', {'hits': []}, {}))

    def test_no_usable_model_means_no_call(self):
        with mock.patch.object(ai_answer, 'provider_for_answer', return_value=(None, {})), \
             mock.patch.object(ai_answer, 'passages') as passages:
            self.assertIsNone(ai_answer.compose('질문', {'hits': []}, {}))
        passages.assert_not_called()


if __name__ == '__main__':
    unittest.main()
