"""BC2-01: fixed language examples, no legal entitlement expected or model calls.

Ported from the teammate branch. A question without a stated status still reads the
local decree here and says so, and the desktop status is applied by institution_matching.
"""
import unittest
from app import personnel_scope
from app import knowledge_intent


LOCAL = {'official': {'title': '지방공무원 복무규정', 'article': '제7조'},
         'institution': '지방자치단체', 'effective_date': '2026-10-02'}

NON_WORKERS = [
    ('지방직인데 연가 사용 기간제한이 있나요?', 'local'),
    ('지방직인데 연가 사용 기간 제한이 있나요?', 'local'),
    ('국가직인데 신청기간제한이 있나요?', 'national'),
    ('지방직인데 연가 사용기간제한은?', 'local'),
    ('지방직인데 신청 기간제한을 알려주세요.', 'local'),
    ('지방직인데 신청기간 제한을 알려주세요.', 'local'),
    ('지방직 연가 기간제한, 적용되나요?', 'local'),
    ('지방직: 연가 기간제한?', 'local'),
    ('신청기간제한이 있나요?', None),
    ('연가 사용 기간 제한이 있나요?', None),
]

WORKERS = [
    '기간제 근로자입니다.', '기간제로 근무하고 있습니다.',
    '무기계약직인데요.', '공무직입니다.', '기간제',
    '기간제입니다.', '기간제인데요.', '기간제 직원으로 근무합니다.',
    '기간제근로자 연차 기준은?', '기간제 근로자: 연차 기준은?',
    '저는 기간제로 6년 근무했습니다.', '무기 계약 근로자입니다.',
    '기간제 한 명으로 근무하고 있습니다.', '기간제한테 적용할 연차 기준은?',
    '계약기간 제한이 있는 기간제 근로자입니다.',
]


class PersonnelWordBoundaries(unittest.TestCase):
    def test_period_limit_compounds_do_not_declare_worker(self):
        for query, framework in NON_WORKERS:
            with self.subTest(query=query):
                got = personnel_scope.analyze(query)
                self.assertEqual(got['framework'], framework)
                self.assertNotIn('public_worker', got['roles'])
                self.assertFalse(got['conflict'])

    def test_local_period_limit_does_not_block_local_source_as_worker(self):
        for query, framework in NON_WORKERS:
            if framework == 'local':
                with self.subTest(query=query):
                    self.assertFalse(knowledge_intent.scope_reason(query, LOCAL, None))

    def test_real_employment_phrases_still_declare_worker(self):
        for query in WORKERS:
            with self.subTest(query=query):
                self.assertIn('public_worker', personnel_scope.analyze(query)['roles'])
                self.assertTrue(knowledge_intent.scope_reason(query, LOCAL, None))

    def test_national_source_keeps_a_period_limit_question(self):
        national = {'official': {'title': '국가공무원 복무규정'},
                    'institution': '국가공무원', 'effective_date': '2026-10-02'}
        self.assertFalse(knowledge_intent.scope_reason('국가직인데 신청기간제한이 있나요?', national, None))

    def test_conflicting_framework_contract(self):
        mixed = personnel_scope.analyze('국가직과 지방직의 신청기간제한을 비교해 주세요.')
        self.assertTrue(mixed['conflict'])
        self.assertIsNone(mixed['framework'])
        self.assertNotIn('public_worker', mixed['roles'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
