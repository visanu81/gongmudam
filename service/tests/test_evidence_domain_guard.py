"""Regression coverage for keeping evidence inside the question's domain."""
import json
from pathlib import Path
from unittest.mock import patch

from test_core import Base, ROOT
from app import knowledge, llm, main


class EvidenceDomainGuardTest(Base):
    def setUp(self):
        knowledge.initialize()
        root = ROOT / 'reference_data' / 'official-20261020'
        rows = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
        self.sources = []
        for row in rows:
            text = (root / 'excerpts' / row['filename']).read_text(encoding='utf-8')
            source_id = row['sha256'][:20]
            self.sources.append(dict(
                id=source_id, title=row['title'] + ' ' + row['article'], enabled=True,
                current=True, sha256=row['sha256'], effective_date=row['effective_date'],
                kind=row['kind'], institution=row['institution'], limited=False,
                library_id='public', file_id=source_id,
                units=[dict(text=text, loc='보관 본문')], official=row,
            ))

    def ask(self, query, **kwargs):
        with patch.object(knowledge, 'sources', return_value=self.sources), \
                patch.object(llm, 'get_provider', side_effect=AssertionError('AI off')):
            return main.api_ask(dict(query=query, guidance=True, use_ai=False,
                                     today='2026-10-25', **kwargs))

    def assert_source_unavailable(self, query):
        result = self.ask(query)['knowledge']
        self.assertEqual(result['mode'], 'source_unavailable')
        self.assertEqual(result['evidence'], [])

    def test_overtime_meal_questions_abstain_without_direct_authority(self):
        for query in (
            '초과근무 식비를 지급하려면 어떤 증빙이 필요한가요?',
            '시간외근무 급식비를 지급하려면 무엇을 증빙해야 하나요?',
            '야근 식대 지급 증빙은 무엇인가요?',
            '특근매식비 지급에 필요한 증빙을 알려주세요.',
        ):
            with self.subTest(query=query):
                self.assert_source_unavailable(query)

    def test_external_roster_privacy_questions_abstain_without_direct_authority(self):
        for query in (
            '교육 취합 명단을 외부에 보낼 때 개인정보를 어떻게 가려야 하나요?',
            '주민등록번호가 포함된 교육 명단을 외부 제공할 때 어떻게 처리해야 하나요?',
            '교육생 명단 외부 제공 전에 개인정보를 어떻게 마스킹하나요?',
        ):
            with self.subTest(query=query):
                self.assert_source_unavailable(query)

    def test_mixed_travel_and_overtime_meal_question_does_not_answer_only_travel(self):
        result = self.ask('출장 식비와 초과근무 식비를 각각 지급하려면 어떤 증빙이 필요한가요?')['knowledge']
        self.assertIn(result['mode'], ('source_unavailable', 'source_clarification'))
        self.assertFalse(result['evidence'])

    def test_supported_questions_keep_their_direct_evidence(self):
        cases = (
            ('관내출장 4시간 공용차량 여비', '공무원 여비 규정'),
            ('지방공무원 공가 헌혈', '지방공무원 복무규정'),
            ('국가공무원인데 병가 진단서는 언제 필요한가요?', '국가공무원 복무규정'),
            ('물품구매 사무용품은 무슨 목으로 사나요?', '지방자치단체 예산편성 운영기준'),
        )
        for query, title_fragment in cases:
            with self.subTest(query=query):
                evidence = self.ask(query)['knowledge']['evidence']
                self.assertTrue(evidence)
                self.assertTrue(any(title_fragment in hit['official']['title'] for hit in evidence))

    def test_incidental_privacy_context_does_not_hide_supported_sick_leave(self):
        for query in (
            '개인정보 업무 담당자인 국가공무원인데 본인이 아파 병가를 쓰려면 진단서가 필요한가요?',
            '개인정보 보호 업무를 담당하는 국가공무원인데 본인 병가를 처리하려면 진단서가 필요한가요?',
            '개인정보 보호 담당 국가공무원인데 본인 병가 처리에 필요한 진단서를 알려주세요.',
        ):
            with self.subTest(query=query):
                result = self.ask(query)['knowledge']
                self.assertTrue(result['evidence'])
                self.assertTrue(any(hit['official']['title'] == '국가공무원 복무규정'
                                    and hit['official']['article'].startswith('제18조')
                                    for hit in result['evidence']))

    def test_direct_registered_context_is_searchable_without_cross_reference(self):
        # Synthetic retrieval fixtures establish no real-world legal entitlement.
        for query, title, text in (
            ('초과근무 식비 지급 증빙은?', '특근매식비 집행 지침', '초과근무 식비의 증빙은 별도 양식으로 제출하여야 한다.'),
            ('초과근무 식비 지급 증빙은?', '초과근무 식비 지급 지침', '초과근무 식비의 증빙은 별도 양식으로 제출하여야 한다.'),
            ('야근 식대 지급 증빙은?', '야근 식대 지급 지침', '야근 식대의 증빙은 별도 양식으로 제출하여야 한다.'),
            ('교육 명단 개인정보를 어떻게 가려야 하나요?', '개인정보 처리 지침', '개인정보를 제공할 때에는 처리 목적을 확인하여야 한다.'),
        ):
            with self.subTest(query=query):
                source=dict(id='context', title=title, enabled=True, current=True, official=None,
                    sha256='a'*64, effective_date='', kind='기관 지침', institution='검증용',
                    limited=False, library_id='public', file_id='context', units=[dict(text=text, loc='1행')])
                self.sources=[source]
                reply=self.ask(query)['knowledge']
                self.assertTrue(reply['evidence'])
                self.assertIn(text,reply['evidence'][0]['text'])

    def test_privacy_guard_also_applies_outside_guidance_mode(self):
        with patch.object(knowledge, 'sources', return_value=self.sources), \
                patch.object(llm, 'get_provider', side_effect=AssertionError('AI off')):
            reply=main.api_ask(dict(query='교육 취합 명단을 외부에 보낼 때 개인정보를 어떻게 가려야 하나요?', use_ai=False))
        self.assertEqual(reply['mode'],'source_unavailable')
        self.assertFalse(reply['knowledge']['evidence'])
