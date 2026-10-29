"""National conduct guideline: integrity, scope and its place below the decree."""
from datetime import date
from unittest.mock import patch
from test_core import Base
from app import service_guidelines, knowledge, llm

TODAY = date(2026, 10, 29)


class ServiceGuidelinesTest(Base):
    def setUp(self):
        service_guidelines.catalog.cache_clear()

    def retrieve(self, query):
        with patch.object(llm, 'get_provider', side_effect=AssertionError('AI is disabled')):
            return knowledge.retrieve(query, None, TODAY)

    def test_all_twelve_chapters_are_verified(self):
        manifest, units = service_guidelines.catalog()
        self.assertEqual(manifest['publication'], '인사혁신처예규 제225호')
        self.assertEqual(len({u['chapter'] for u in units}), 12)
        self.assertTrue(all(len(u['text']) <= service_guidelines.WINDOW * 2 for u in units))

    def test_changed_sections_file_disables_the_guideline(self):
        with patch.object(service_guidelines, 'BASE', service_guidelines.BASE.parent / 'missing-guideline'):
            service_guidelines.catalog.cache_clear()
            self.assertEqual(service_guidelines.search('국가공무원 반일연가 기준'), [])
        service_guidelines.catalog.cache_clear()

    def test_answers_operating_question_without_an_article(self):
        found = self.retrieve('국가공무원 반일연가는 몇 시 기준으로 오전 오후를 나누나요?')
        self.assertTrue(found['hits'])
        self.assertTrue(all(h['library_id'] == service_guidelines.LIBRARY for h in found['hits']))
        self.assertIn('14:00', found['hits'][0]['text'])
        self.assertIn('예규', found['service_notice'])

    def test_article_stays_evidence_and_guideline_is_practice(self):
        found = self.retrieve('국가공무원 병가는 연간 며칠까지 쓸 수 있나요?')
        self.assertTrue(found['hits'][0]['title'].startswith('국가공무원 복무규정 제18조('))
        self.assertTrue(all(h['library_id'] != service_guidelines.LIBRARY for h in found['hits']))
        self.assertEqual([p['library_id'] for p in found['practice']], [service_guidelines.LIBRARY])

    def test_not_used_for_local_officers_amounts_or_other_domains(self):
        for query in ('지방공무원 유연근무 신청 방법은?', '징계 감봉은 보수를 얼마나 줄이나요?',
                      '초과근무 식비 집행하려면 어떤 근거가 필요한가요?', '교사 유연근무 신청은 어떻게 하나요?'):
            with self.subTest(query=query):
                found = self.retrieve(query)
                self.assertFalse(any(h['library_id'] == service_guidelines.LIBRARY for h in found['hits']))
                self.assertFalse(found.get('practice'))

    def test_section_titles_lead_the_ranking(self):
        for query, title in (('공무원증 분실하면 어떻게 하나요?', '공무원증 분실자'),
                             ('징계위원회는 어떻게 구성하나요?', '징계위원회의 구성')):
            with self.subTest(query=query):
                self.assertIn(title, service_guidelines.search(query)[0]['loc'])
