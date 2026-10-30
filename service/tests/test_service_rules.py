"""Bundled conduct regulations: integrity, status routing, reviewed AI-free answers."""
import json
import re
import shutil
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch
from test_core import Base
from app import service_rules, knowledge, answer_tree, llm, knowledge_intent

CHECKS = Path(__file__).resolve().parents[1] / 'reference_data/service_rules_checks.json'
TODAY = date(2026, 10, 29)


class ServiceRulesTest(Base):
    def setUp(self):
        service_rules.catalog.cache_clear()
        service_rules.summaries.cache_clear()

    def ask(self, query):
        with patch.object(llm, 'get_provider', side_effect=AssertionError('AI is disabled')):
            found = knowledge.retrieve(query, None, TODAY)
            reply = knowledge.answer(query, found, use_ai=False)
        return reply, answer_tree.build(query, reply)

    def test_all_four_regulations_are_hash_verified(self):
        rows = [row for row, _ in service_rules.catalog()]
        counts = {law: sum(r['law'] == law for r in rows) for law in service_rules.TITLES}
        self.assertEqual(counts, {'national': 46, 'local': 32, 'fire': 13, 'police': 20, 'gyeonggi': 16,
                                  'national_allowance': 33, 'local_allowance': 31, 'welfare': 27, 'national_rules': 58})
        self.assertTrue(all(r['source_url'].startswith('https://www.law.go.kr/') for r in rows))

    def test_changed_article_text_is_dropped(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            copy = tmp / service_rules.COLLECTION
            shutil.copytree(service_rules.BASE, copy)
            target = copy / 'excerpts' / '경찰공무원 복무규정_제9조.txt'
            target.write_text(target.read_text(encoding='utf-8').replace('아니된다', '된다'), encoding='utf-8')
            with patch.object(service_rules, 'BASE', copy):
                service_rules.catalog.cache_clear()
                articles = {r['id'] for r, _ in service_rules.catalog()}
            self.assertNotIn('police-9', articles)
            self.assertIn('police-18', articles)
        finally:
            service_rules.catalog.cache_clear()
            shutil.rmtree(tmp, ignore_errors=True)

    def test_stale_registered_article_does_not_hide_bundled_article(self):
        bundled = next(service_rules.document(r, t) for r, t in service_rules.catalog() if r['id'] == 'local-7')
        stale = dict(bundled, id='registered', sha256='0' * 64, current=False,
                     official=dict(bundled['official'], sha256='0' * 64))
        with patch.object(knowledge, 'sources', return_value=[stale]), \
                patch.object(knowledge.official_sources, 'metadata', return_value={'title': 'x'}):
            found = knowledge.retrieve('지방공무원 연가 일수는 며칠인가요?', None, TODAY)
        self.assertEqual([h['source_id'] for h in found['hits']][:1], ['service-rules:local-7'])

    def test_every_reviewed_sentence_has_its_anchor_in_the_article(self):
        texts = {(r['law'], r['article']): t for r, t in service_rules.catalog()}
        for card in service_rules.summaries():
            with self.subTest(card=card['id']):
                text = next(t for (law, article), t in texts.items() if law == card['law'] and article.startswith(card['article']))
                for item in card['items']:
                    for anchor in item['anchors']:
                        self.assertRegex(text, r'\s*'.join(map(re.escape, re.sub(r'\s+', '', anchor))))

    def test_status_selects_regulation_and_special_rule(self):
        self.assertEqual(service_rules.status('소방관 공가'), 'fire')
        self.assertEqual(service_rules.status('경위 승진 후 연가'), 'police')
        self.assertEqual(service_rules.status('시청 근무 연가'), 'local')
        self.assertIsNone(service_rules.status('연가는 며칠인가요'))
        self.assertEqual(service_rules.expected('public_leave', '소방공무원 공가'), ('소방공무원 복무규정', ('제8조의2(',)))
        # Fire officers follow the national regulation where their decree is silent.
        self.assertEqual(service_rules.expected('annual', '소방공무원 연가'), ('국가공무원 복무규정', ('제15조(',)))
        # Without a status the existing local-first leave mapping is kept.
        self.assertIsNone(service_rules.expected('sick', '병가 며칠'))

    def test_province_ordinance_applies_only_to_its_own_officials(self):
        self.assertEqual(service_rules.status('소방청 소속 소방공무원'), 'fire_national')
        self.assertEqual(service_rules.reads('경기도 소속 소방공무원 장기재직'), ('gyeonggi', 'fire', 'national'))
        self.assertEqual(service_rules.reads('경기도 소속 지방공무원'), ('gyeonggi', 'local'))
        self.assertEqual(service_rules.reads('소방청 소속 소방공무원'), ('fire', 'national'))
        # The education office follows its own ordinance, not the province's.
        self.assertIsNone(service_rules.region('경기도교육청 지방공무원'))
        self.assertEqual(service_rules.expected('long_service', '경기도 소속 소방공무원'), ('경기도 공무원 복무 조례', ('제14조(',)))
        self.assertEqual(service_rules.expected('long_service', '소방공무원'), ('소방공무원 복무규정', ('제11조(',)))

    def test_affiliation_adds_status_and_only_an_applicable_province(self):
        from app import institution_matching as matching
        def scope(framework, organization, region, query='장기재직휴가 며칠?'):
            profile = dict(confirmed=True, personnel_framework=framework, organization=organization, region=region, department='')
            return matching.scope_query(query, profile).split(chr(10))[-1]
        self.assertEqual(scope('fire_public_official', '경기도 수원소방서', '경기도'), '업무환경: 경기도 소속 소방공무원')
        self.assertEqual(scope('fire_public_official', '소방청 중앙119구조본부', '세종특별자치시'), '업무환경: 소방청 소속 소방공무원')
        self.assertEqual(scope('local_public_official', '경기도', '경기도'), '업무환경: 경기도 소속 지방공무원')
        # A city follows its own ordinance; the province's is not implied.
        self.assertEqual(scope('local_public_official', '경기도 수원시', '경기도'), '업무환경: 지방공무원')
        self.assertEqual(scope('police_public_official', '경기남부경찰청', '경기도'), '업무환경: 경찰공무원')
        # A question about another status keeps the question's own scope.
        self.assertEqual(scope('local_public_official', '경기도', '경기도', '소방공무원 장기재직휴가는?'), '소방공무원 장기재직휴가는?')

    def test_overtime_is_not_a_business_trip(self):
        plan = knowledge_intent.analyze('시간외근무 명령은 누가 하나요?')
        self.assertEqual(plan['topics'], ['overtime'])
        # An ordinary 외근 is still a trip.
        self.assertIn('travel_daily', knowledge_intent.analyze('외근 나가면 일비 지급 기준이 뭐예요')['topics'])

    def test_reviewed_questions_answer_without_ai(self):
        for case in json.loads(CHECKS.read_text(encoding='utf-8')):
            # Annex tables come from the registered official pack, absent in this empty test library.
            if case.get('registered'):continue
            with self.subTest(case=case['id']):
                reply, tree = self.ask(case['question'])
                first = reply['evidence'][0]['title'] if reply['evidence'] else ''
                if case.get('article'):
                    self.assertTrue(first.startswith(case['article']), first)
                if case.get('rule'):
                    self.assertEqual(tree.get('rule_id'), case['rule'])
                    # Conclusion first: the title is a reviewed, cited sentence.
                    self.assertTrue(all(i['ref'] and i['support_quotes'] for b in tree['branches'] for i in b['items']))
                if case.get('notice'):
                    self.assertIn(case['notice'], reply['notice'])
                if case.get('not_mode'):
                    self.assertNotEqual(reply['mode'], case['not_mode'])
