"""Supplemental office-pack retrieval and add-only registration regressions."""
import json
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from app import knowledge, llm, main, office_knowledge
from tools import register_office_extra_pack


ROOT = Path(__file__).resolve().parents[1]


class OfficeExtraKnowledgeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_manifest = json.loads((office_knowledge.BASE / 'manifest.json').read_text(encoding='utf-8'))
        cls.extra_manifest = json.loads((office_knowledge.EXTRA_BASE / 'manifest.json').read_text(encoding='utf-8'))
        cls.manifest = cls.base_manifest + cls.extra_manifest
        cls.sources = [dict(
            id=row['id'], title=row['title'] + ' ' + row['article'], enabled=True,
            current=True, sha256=row['sha256'], effective_date=row['effective_date'],
            kind=row['kind'], institution=row['institution'], limited=False,
            library_id=row['collection'], file_id=row['id'], units=row['units'], official=row,
        ) for row in cls.manifest]

    def ask(self, query, sources=None, *, use_ai=False):
        with patch.object(knowledge, 'sources', return_value=self.sources if sources is None else sources), \
                patch.object(knowledge.config, 'active_profile', return_value={'provider': 'offline'}), \
                patch.object(knowledge, '_experience_hits', return_value=[]), \
                patch.object(llm, 'get_provider', side_effect=AssertionError('Unexpected AI provider lookup')):
            return main.api_ask(dict(query=query, guidance=True, use_ai=use_ai, today='2026-10-25'))

    def assert_extra_summary(self, result, expected_id, expected_rule):
        self.assertFalse(result['guidance']['ai_used'])
        reply = result['knowledge']
        self.assertFalse(reply.get('model'))
        self.assertEqual(reply['mode'], 'source_search')
        self.assertIsNone(result['model'])
        self.assertTrue(reply['evidence'])
        summary = reply['tree']
        self.assertEqual(summary['kind'], 'summary')
        self.assertEqual(summary['rule_id'], 'office:' + expected_rule)
        self.assertIn('근거', result['answer'])
        self.assertIn(expected_id, {hit['official']['id'] for hit in reply['evidence']})
        expected_hit = next(hit for hit in reply['evidence'] if hit['official']['id'] == expected_id)
        self.assertEqual(expected_hit['official']['collection'], 'office-extra-20261025')
        for branch in summary['branches']:
            for item in branch['items']:
                self.assertTrue(item['support_quotes'])
                hit = reply['evidence'][item['ref'] - 1]
                for quote in item['support_quotes']:
                    self.assertIn(quote, hit['text'])

    def test_supplemental_questions_have_complete_supported_summaries(self):
        cases = (
            ('아동 만 14세 미만 개인정보 동의는?', 'office-extra-privacy-art22-2', 'privacy-child'),
            ('개인정보 열람 요구를 거절할 수 있나요?', 'office-extra-privacy-art35', 'privacy-access'),
            ('개인정보 정정 삭제를 요구할 수 있나요?', 'office-extra-privacy-art36', 'privacy-rectify'),
            ('개인정보 처리정지와 동의 철회는?', 'office-extra-privacy-art37', 'privacy-stop'),
            ('개인정보 처리업무 위탁 계약은 어떻게 하나요?', 'office-extra-privacy-art26', 'privacy-outsource'),
            ('기록물 등록번호 수정 삭제가 가능한가요?', 'office-extra-records-decree-20', 'records-register-detail'),
            ('회의록 작성 대상과 작성 항목은?', 'office-extra-records-decree-18', 'records-meeting-detail'),
            ('기록물 보존기간 책정 기준은?', 'office-extra-records-decree-26', 'records-retention-detail'),
            ('기록물 평가 폐기 절차는?', 'office-extra-records-decree-43', 'records-disposal-detail'),
            ('정보공개 수수료 감면 기준은?', 'office-extra-disclosure-17', 'disclosure-fees'),
            ('반복 청구한 정보공개를 종결할 수 있나요?', 'office-extra-disclosure-11-2', 'disclosure-repeat'),
        )
        for query, expected_id, expected_rule in cases:
            with self.subTest(query=query):
                self.assert_extra_summary(self.ask(query), expected_id, expected_rule)

    def test_uncollected_details_and_unsupported_queries_abstain(self):
        for query in (
            '개인정보 열람요구 처리기한은?',
            '개인정보 유출 과태료는 얼마인가요?',
            '2020년 정보공개 수수료 감면 기준은?',
        ):
            with self.subTest(query=query):
                self.assertFalse(self.ask(query)['knowledge']['evidence'])

    def test_natural_particles_and_repeated_claim_phrases_keep_the_right_procedure(self):
        for query,sid,rule in (
            ('개인정보 삭제를 요구할 수 있나요?','office-extra-privacy-art36','privacy-rectify'),
            ('개인정보 삭제를 요청했어요','office-extra-privacy-art36','privacy-rectify'),
            ('개인정보 처리에 대한 동의를 철회할 수 있나요?','office-extra-privacy-art37','privacy-stop'),
            ('정보공개를 반복해서 청구한 경우 어떻게 처리하나요?','office-extra-disclosure-11-2','disclosure-repeat'),
        ):
            self.assert_extra_summary(self.ask(query),sid,rule)

    def test_missing_disabled_and_tampered_extra_source_abstain(self):
        query = '개인정보 열람 요구를 거절할 수 있나요?'
        target = next(row for row in self.sources if row['id'] == 'office-extra-privacy-art35')
        self.assertFalse(self.ask(query, [row for row in self.sources if row['id'] != target['id']])['knowledge']['evidence'])
        for field in ('enabled', 'current'):
            disabled = [dict(row) for row in self.sources]
            next(row for row in disabled if row['id'] == target['id'])[field] = False
            with self.subTest(field=field):
                self.assertFalse(self.ask(query, disabled)['knowledge']['evidence'])

        with tempfile.TemporaryDirectory() as folder:
            extra = Path(folder) / 'office-extra'
            shutil.copytree(office_knowledge.EXTRA_BASE, extra)
            excerpt = extra / 'excerpts' / target['official']['filename']
            excerpt.write_text(excerpt.read_text(encoding='utf-8') + '\ntampered', encoding='utf-8')
            with patch.object(office_knowledge, 'EXTRA_BASE', extra):
                self.assertFalse(self.ask(query)['knowledge']['evidence'])

    def make_db(self, path):
        with closing(sqlite3.connect(path)) as connection:
            connection.execute('CREATE TABLE libraries(id TEXT PRIMARY KEY,version INTEGER,payload TEXT)')
            connection.execute('CREATE TABLE knowledge_sources(id TEXT PRIMARY KEY,library_id TEXT,file_id TEXT,enabled INTEGER,payload TEXT,UNIQUE(library_id,file_id))')
            connection.execute('CREATE TABLE business_rows(id TEXT PRIMARY KEY,value TEXT)')
            connection.execute('INSERT INTO libraries VALUES(?,?,?)', ('office-20261025', 1, '{"name":"base pack"}'))
            connection.execute('INSERT INTO libraries VALUES(?,?,?)', ('personal', 3, '{"private":"keep"}'))
            connection.execute('INSERT INTO knowledge_sources VALUES(?,?,?,?,?)',
                               ('office-base-source', 'office-20261025', 'office-base-source', 1, '{"sha256":"base"}'))
            connection.execute('INSERT INTO knowledge_sources VALUES(?,?,?,?,?)',
                               ('business-source', 'personal', 'business-file', 0, '{"sha256":"existing"}'))
            connection.execute('INSERT INTO business_rows VALUES(?,?)', ('row1', 'preserve'))
            connection.commit()

    def test_extra_registration_dry_run_apply_and_idempotency_preserve_existing_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            extra = root / 'office-extra-pack'
            shutil.copytree(office_knowledge.EXTRA_BASE, extra)
            db = root / 'folders.db'
            self.make_db(db)
            with patch.object(office_knowledge, 'EXTRA_BASE', extra):
                dry = register_office_extra_pack.register(db)
                self.assertEqual(len(dry['would_add']), len(self.extra_manifest))
                self.assertEqual(dry['added'], [])
                self.assertIsNone(dry['backup'])
                with closing(sqlite3.connect(db)) as connection:
                    self.assertEqual(connection.execute('SELECT COUNT(*) FROM knowledge_sources').fetchone()[0], 2)
                applied = register_office_extra_pack.register(db, apply=True)
                self.assertEqual(len(applied['added']), len(self.extra_manifest))
                again = register_office_extra_pack.register(db, apply=True)
                self.assertEqual(again['would_add'], [])
                self.assertEqual(again['added'], [])
                with closing(sqlite3.connect(db)) as connection:
                    self.assertEqual(connection.execute('SELECT COUNT(*) FROM knowledge_sources').fetchone()[0], len(self.extra_manifest) + 2)
                    self.assertEqual(connection.execute('SELECT * FROM business_rows').fetchall(), [('row1', 'preserve')])
                    self.assertEqual(connection.execute('SELECT payload FROM libraries WHERE id="personal"').fetchone()[0], '{"private":"keep"}')
                    self.assertEqual(connection.execute('SELECT payload FROM libraries WHERE id="office-20261025"').fetchone()[0], '{"name":"base pack"}')
                    self.assertEqual(connection.execute('SELECT enabled FROM knowledge_sources WHERE id="business-source"').fetchone()[0], 0)

    def test_extra_registration_rejects_tampered_source_without_database_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            extra = root / 'office-extra-pack'
            shutil.copytree(office_knowledge.EXTRA_BASE, extra)
            db = root / 'folders.db'
            self.make_db(db)
            manifest_path = extra / 'manifest.json'
            rows = json.loads(manifest_path.read_text(encoding='utf-8'))
            rows[0]['sha256'] = '0' * 64
            manifest_path.write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
            with patch.object(office_knowledge, 'EXTRA_BASE', extra):
                with self.assertRaisesRegex(ValueError, 'validation failed'):
                    register_office_extra_pack.register(db, apply=True)
            with closing(sqlite3.connect(db)) as connection:
                self.assertEqual(connection.execute('SELECT COUNT(*) FROM knowledge_sources').fetchone()[0], 2)
                self.assertEqual(connection.execute('SELECT * FROM business_rows').fetchall(), [('row1', 'preserve')])


if __name__ == '__main__':
    unittest.main()
