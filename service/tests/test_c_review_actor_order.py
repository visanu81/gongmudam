"""A preceding other-actor declaration must not erase the explicit self clause."""
import unittest
from app import personnel_scope


class ReviewActorOrder(unittest.TestCase):
    def test_spouse_before_self_keeps_self_framework_and_role(self):
        scope=personnel_scope.analyze('배우자는 교원이고 나는 국가직 일반직입니다. 내 병가 근거를 알려줘')
        self.assertEqual(scope['framework'],'national');self.assertEqual(scope['roles'],['general'])

    def test_colleague_before_self_keeps_explicit_self_framework(self):
        scope=personnel_scope.analyze('동료는 지방직이고 저는 국가직 일반직입니다. 제 병가를 알려줘')
        self.assertEqual(scope['framework'],'national');self.assertEqual(scope['roles'],['general'])
        self.assertFalse(scope['conflict'])

    def test_inline_organization_does_not_erase_following_self_clause(self):
        for query,framework in [
            ('소속기관: 합성기관, 저는 국가직 일반직입니다. 제 병가 기준을 알려줘','national'),
            ('기관명: 합성기관이고 나는 지방직 일반직입니다. 내 병가를 알려줘','local'),
            ('소속기관: 국가공무원인재개발원. 나는 지방직 일반직입니다. 내 병가 기준은?','local'),
        ]:
            with self.subTest(query=query):
                scope=personnel_scope.analyze(query)
                self.assertEqual(scope['framework'],framework);self.assertEqual(scope['roles'],['general'])
