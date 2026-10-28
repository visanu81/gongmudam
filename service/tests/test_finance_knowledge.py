"""Finance-pack retrieval and registration regressions using temporary state."""
import json
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path
from unittest.mock import patch

from app import finance_knowledge, knowledge, llm, main
from tools import register_finance_pack


ROOT = Path(__file__).resolve().parents[1]


class FinanceKnowledgeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((finance_knowledge.BASE / 'manifest.json').read_text(encoding='utf-8'))
        cls.sources = []
        for row in cls.manifest:
            cls.sources.append(dict(
                id=row['id'], title=row['title'] + ' ' + row['article'], enabled=True,
                current=True, sha256=row['sha256'], effective_date=row['effective_date'],
                kind=row['kind'], institution=row['institution'], limited=False,
                library_id='finance-test', file_id=row['id'], units=row['units'], official=row,
            ))

    def ask(self, query, sources=None):
        with patch.object(knowledge, 'sources', return_value=sources or self.sources), \
                patch.object(knowledge.config, 'active_profile', return_value={'provider': 'offline'}), \
                patch.object(knowledge, '_experience_hits', return_value=[]), \
                patch.object(llm, 'get_provider', side_effect=AssertionError('AI must remain off')):
            return main.api_ask(dict(query=query, guidance=True, use_ai=False, today='2026-10-25'))

    def test_supported_topics_return_exact_scope_and_source_quotes(self):
        cases = (
            ('국가기관 초과근무 식비 지급 대상과 제외 조건은?', 'overtime_meal', 'national_government', '시간외 근무수당을 지급받고 있는 자'),
            ('지방자치단체 초과근무 식비의 예외와 금지 조건은?', 'overtime_meal', 'local_government', '급식을 제공받는공무원에게현금으로'),
            ('국가기관 회의 식비 집행 기준은?', 'meeting_meal', 'national_government', '공식 회의 및 행사 경비'),
            ('지방자치단체 회의 식비 집행 기준은?', 'meeting_meal', 'local_government', '업무추진비'),
            ('국가기관 외부강사 강사료 기준은?', 'lecturer', 'national_government', '강사료 지급'),
            ('지방자치단체 외부강사 강사료 기준은?', 'lecturer', 'local_government', '공무원교육외래강사료'),
            ('국가기관 법인카드 사용 기준은?', 'card', 'national_government', '정부구매카드'),
            ('지방자치단체 구매카드 사용 기준은?', 'card', 'local_government', '지방자치단체구매카드'),
            ('국가기관 사무용품 예산 집행 기준은?', 'office_supplies', 'national_government', '소모성 물품구입비'),
            ('지방자치단체 사무용품 예산 집행 기준은?', 'office_supplies', 'local_government', '사무관리비'),
            ('국가기관 자산 취득비 기준은?', 'assets', 'national_government', '자산취득비'),
            ('지방자치단체 자산 취득비 기준은?', 'assets', 'local_government', '자산취득비'),
        )
        for query, topic, scope, quote_fragment in cases:
            with self.subTest(query=query):
                evidence = self.ask(query)['knowledge']['evidence']
                self.assertTrue(evidence)
                self.assertTrue(all(hit['official']['finance_scope'] == scope for hit in evidence))
                matching = [hit for hit in evidence if topic in hit['official']['finance_topics']]
                self.assertTrue(matching)
                self.assertTrue(any(quote_fragment in hit['text'] for hit in matching))
                self.assertTrue(all(hit['quote'] in hit['text'] for hit in evidence))
                self.assertTrue(all(hit['loc'] and hit['official']['units'][0]['loc'] in hit['loc'] for hit in evidence))

    def test_local_overtime_excerpt_retains_exclusions_cash_ban_and_page_69(self):
        query = '지방자치단체 초과근무 식비 지급 대상, 제외 대상, 현금 지급 금지 조건은?'
        evidence = self.ask(query)['knowledge']['evidence']
        self.assertTrue(evidence)
        hit = next(hit for hit in evidence if hit['official']['finance_scope'] == 'local_government')
        self.assertIn('PDF 68쪽 / PDF 69쪽', hit['loc'])
        for phrase in ('제외한다', '현금으로\n지급해서는안된다'):
            self.assertIn(phrase, hit['text'])
        self.assertIn(69, hit['official']['pdf_pages'])

    def test_ambiguous_unsupported_wrong_year_and_future_local_sources_abstain(self):
        queries = (
            '초과근무 식비 지급 기준은?',
            '교육청 초과근무 식비 지급 기준은?',
            '국가기관과 지방자치단체의 2026년도 초과근무 식비 기준은?',
            '지방자치단체 2027년도 초과근무 식비 기준은?',
            '지방자치단체 2027-01-01 기준으로 초과근무 식비는?',
            '지방자치단체 2026-05-01 기준으로 초과근무 식비는?',
        )
        for query in queries:
            with self.subTest(query=query):
                result = self.ask(query)['knowledge']
                self.assertFalse(result['evidence'])

    def test_privacy_question_does_not_get_finance_evidence(self):
        result = self.ask('교육 취합 명단을 외부에 보낼 때 개인정보를 어떻게 가려야 하나요?')['knowledge']
        self.assertFalse(result['evidence'])

    def test_national_meeting_common_conditions_and_compound_questions(self):
        reply=self.ask('국가기관 회의 식비와 강사료 집행 기준은?')['knowledge']
        covered={t for hit in reply['evidence'] for t in hit['official']['finance_topics']}
        self.assertTrue({'meeting_meal','lecturer'} <= covered)
        meeting=next(hit for hit in reply['evidence'] if 'meeting_meal' in hit['official']['finance_topics'])
        for phrase in ('클린카드','50만원','심야시간대','증빙서류'):
            self.assertIn(phrase,meeting['text'])
        mixed=self.ask('국가기관 출장 식비와 초과근무 식비를 각각 지급하려면?')['knowledge']
        self.assertFalse(mixed['evidence'])

    def make_temp_pack(self, parent):
        target = parent / 'finance-pack'
        shutil.copytree(finance_knowledge.BASE, target)
        return target

    def make_db(self, path):
        connection = sqlite3.connect(path)
        try:
            connection.execute('CREATE TABLE libraries(id TEXT PRIMARY KEY,version INTEGER,payload TEXT)')
            connection.execute('CREATE TABLE knowledge_sources(id TEXT PRIMARY KEY,library_id TEXT,file_id TEXT,enabled INTEGER,payload TEXT,UNIQUE(library_id,file_id))')
            connection.execute('CREATE TABLE business_rows(id TEXT PRIMARY KEY,value TEXT)')
            connection.execute('INSERT INTO libraries VALUES(?,?,?)', ('personal', 3, '{"private":"keep"}'))
            connection.execute('INSERT INTO knowledge_sources VALUES(?,?,?,?,?)',
                               ('business-source', 'personal', 'business-file', 0, '{"sha256":"existing"}'))
            connection.execute('INSERT INTO business_rows VALUES(?,?)', ('row1', 'preserve'))
            connection.commit()
        finally:
            connection.close()

    def test_register_dry_run_add_and_idempotency_preserve_existing_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pack = self.make_temp_pack(root)
            db = root / 'folders.db'
            self.make_db(db)
            with patch.object(finance_knowledge, 'BASE', pack):
                dry = register_finance_pack.register(db)
                self.assertEqual(len(dry['would_add']), 14)
                self.assertEqual(dry['added'], [])
                with closing(sqlite3.connect(db)) as connection:
                    self.assertEqual(connection.execute('SELECT COUNT(*) FROM knowledge_sources').fetchone()[0], 1)
                applied = register_finance_pack.register(db, apply=True)
                self.assertEqual(len(applied['added']), 14)
                again = register_finance_pack.register(db, apply=True)
                self.assertEqual(again['would_add'], [])
                self.assertEqual(again['added'], [])
                with closing(sqlite3.connect(db)) as connection:
                    self.assertEqual(connection.execute('SELECT COUNT(*) FROM knowledge_sources').fetchone()[0], 15)
                    self.assertEqual(connection.execute('SELECT * FROM business_rows').fetchall(), [('row1', 'preserve')])
                    self.assertEqual(connection.execute('SELECT payload FROM libraries WHERE id="personal"').fetchone()[0], '{"private":"keep"}')
                    self.assertEqual(connection.execute('SELECT enabled FROM knowledge_sources WHERE id="business-source"').fetchone()[0], 0)

    def test_register_rejects_tampered_pack_metadata_without_touching_database(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pack = self.make_temp_pack(root)
            db = root / 'folders.db'
            self.make_db(db)
            manifest_path = pack / 'manifest.json'
            rows = json.loads(manifest_path.read_text(encoding='utf-8'))
            rows[0]['sha256'] = '0' * 64
            manifest_path.write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
            with patch.object(finance_knowledge, 'BASE', pack):
                with self.assertRaisesRegex(ValueError, 'validation failed'):
                    register_finance_pack.register(db, apply=True)
            with closing(sqlite3.connect(db)) as connection:
                self.assertEqual(connection.execute('SELECT COUNT(*) FROM knowledge_sources').fetchone()[0], 1)
                self.assertEqual(connection.execute('SELECT * FROM business_rows').fetchall(), [('row1', 'preserve')])


if __name__ == '__main__':
    unittest.main()
