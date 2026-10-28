"""Document-workflow office-pack retrieval and immutable-registration regressions."""
import hashlib
import json
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import knowledge, llm, main, manual_knowledge, office_knowledge
from tools import prepare_document_pack, register_office_documents_pack


class OfficeDocumentKnowledgeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((office_knowledge.DOCUMENT_BASE / 'manifest.json').read_text(encoding='utf-8'))
        cls.sources = [dict(
            id=row['id'], title=row['title'] + ' ' + row['article'], enabled=True,
            current=True, sha256=row['sha256'], effective_date=row['effective_date'],
            kind=row['kind'], institution=row['institution'], limited=False,
            library_id=row['collection'], file_id=row['id'], units=row['units'], official=row,
        ) for row in cls.manifest]

    def ask(self, query, sources=None):
        with patch.object(knowledge, 'sources', return_value=self.sources if sources is None else sources), \
                patch.object(knowledge.config, 'active_profile', return_value={'provider': 'offline'}), \
                patch.object(knowledge, '_experience_hits', return_value=[]), \
                patch.object(llm, 'get_provider', side_effect=AssertionError('Unexpected AI provider lookup')):
            return main.api_ask(dict(query=query, guidance=True, use_ai=False, today='2026-10-26'))

    def assert_document_summary(self, result, expected_ids, rule):
        self.assertFalse(result['guidance']['ai_used'])
        reply = result['knowledge']
        self.assertFalse(reply.get('model'))
        self.assertEqual(reply['mode'], 'source_search')
        self.assertIsNone(result['model'])
        self.assertTrue(reply['evidence'])
        summary = reply['tree']
        self.assertEqual(summary['kind'], 'summary')
        self.assertEqual(summary['rule_id'], 'office:' + rule)
        self.assertIn('근거', result['answer'])
        actual_ids = {hit['official']['id'] for hit in reply['evidence']}
        self.assertTrue(expected_ids <= actual_ids)
        for hit in reply['evidence']:
            self.assertEqual(hit['official']['collection'], 'office-documents-20261026')
        for branch in summary['branches']:
            for item in branch['items']:
                self.assertTrue(item['support_quotes'])
                hit = reply['evidence'][item['ref'] - 1]
                for quote in item['support_quotes']:
                    self.assertIn(quote, hit['text'])

    def test_receipt_and_drafting_questions_have_exact_supported_summaries(self):
        cases = (
            ('공문을 접수한 뒤 담당 부서로 배부하는 절차는?',
             {'office-documents-decree-2', 'office-documents-decree-3',
              'office-documents-decree-18', 'office-documents-rule-15'}, 'documents-receipt'),
            ('공문 기안에서 검토와 결재는 어떤 순서로 하나요?',
             {'office-documents-decree-8', 'office-documents-decree-9',
              'office-documents-decree-10', 'office-documents-decree-11',
              'office-documents-decree-12', 'office-documents-decree-6',
              'office-documents-decree-2'}, 'documents-drafting'),
        )
        for query, expected_ids, rule in cases:
            with self.subTest(query=query):
                self.assert_document_summary(self.ask(query), expected_ids, rule)

    def test_receipt_and_drafting_paraphrases_keep_the_reviewed_rule(self):
        cases = (
            ('문서과에서 받은 공문은 어떻게 배부하나요?', 'documents-receipt'),
            ('기안문 검토는 결재 전에 받나요?', 'documents-drafting'),
            ('공문 결재권자가 출장 중이면 누가 대결하나요?', 'documents-drafting'),
            ('공문은 당직 때 받으면 어떻게 접수하나요?', 'documents-receipt'),
        )
        for query, rule in cases:
            with self.subTest(query=query):
                self.assert_document_summary(self.ask(query), set(), rule)

    def test_unsupported_institution_specific_and_out_of_period_questions_abstain(self):
        for query in (
            '우리 부서 공문 결재선은?',
            '공기업 공문 기안 결재 순서는?',
            '공문 저작권 검토는?',
            '2020년 공문 접수 절차는?',
            '2027년 공문 기안 결재는?',
            '공문 기안 양식파일을 내려받고 싶어요',
        ):
            with self.subTest(query=query):
                self.assertFalse(self.ask(query)['knowledge']['evidence'])

        internal = self.ask('우리 부서 공문 결재선은?')
        self.assertFalse(internal['knowledge']['evidence'])
        self.assertTrue(any(term in internal['knowledge']['notice'] for term in ('세부', '자료')))
        self.assertIsNone(manual_knowledge.classify('공문 결재선은?'))
        self.assertEqual(manual_knowledge.classify('e-사람 출장 결재선 변경 방법')['family'], 'travel')

    def test_missing_disabled_changed_and_tampered_required_sources_abstain(self):
        query = '공문을 접수한 뒤 담당 부서로 배부하는 절차는?'
        required = next(row for row in self.sources if row['id'] == 'office-documents-decree-18')
        self.assertFalse(self.ask(query, [row for row in self.sources if row['id'] != required['id']])['knowledge']['evidence'])
        for field in ('enabled', 'current'):
            changed = [dict(row) for row in self.sources]
            next(row for row in changed if row['id'] == required['id'])[field] = False
            with self.subTest(field=field):
                self.assertFalse(self.ask(query, changed)['knowledge']['evidence'])

        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder) / 'office-documents'
            shutil.copytree(office_knowledge.DOCUMENT_BASE, base)
            excerpt = base / 'excerpts' / required['official']['filename']
            excerpt.write_text(excerpt.read_text(encoding='utf-8') + '\ntampered', encoding='utf-8')
            with patch.object(office_knowledge, 'DOCUMENT_BASE', base):
                self.assertFalse(self.ask(query)['knowledge']['evidence'])

            raw_pack = Path(folder) / 'office-documents-raw-tamper'
            shutil.copytree(office_knowledge.DOCUMENT_BASE, raw_pack)
            raw_file = raw_pack / 'raw' / required['official']['raw_file']
            raw_file.write_bytes(raw_file.read_bytes() + b' tampered')
            with patch.object(office_knowledge, 'DOCUMENT_BASE', raw_pack):
                self.assertFalse(self.ask(query)['knowledge']['evidence'])

    def test_original_endpoint_serves_hashed_plain_text_not_html(self):
        source = self.manifest[0]
        client = TestClient(main.app)
        response = client.get(f"/api/office-sources/{source['sha256']}/original")
        excerpt = (office_knowledge.DOCUMENT_BASE / 'excerpts' / source['filename']).read_text(encoding='utf-8')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers['content-type'].startswith('text/plain'))
        self.assertIn(excerpt, response.text)
        self.assertEqual(hashlib.sha256(excerpt.encode('utf-8')).hexdigest(), source['sha256'])
        self.assertNotIn('<html', response.text.lower())

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

    def test_registration_is_add_only_and_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            base = root / 'office-documents-pack'
            shutil.copytree(office_knowledge.DOCUMENT_BASE, base)
            db = root / 'folders.db'
            self.make_db(db)
            with patch.object(office_knowledge, 'DOCUMENT_BASE', base):
                dry = register_office_documents_pack.register(db)
                self.assertEqual(len(dry['would_add']), 10)
                self.assertEqual(dry['added'], [])
                self.assertIsNone(dry['backup'])
                applied = register_office_documents_pack.register(db, apply=True)
                self.assertEqual(len(applied['added']), 10)
                self.assertTrue(applied['backup'])
                again = register_office_documents_pack.register(db, apply=True)
                self.assertEqual(again['would_add'], [])
                self.assertEqual(again['added'], [])
                with closing(sqlite3.connect(db)) as connection:
                    self.assertEqual(connection.execute('SELECT COUNT(*) FROM knowledge_sources').fetchone()[0], 12)
                    self.assertEqual(connection.execute('SELECT * FROM business_rows').fetchall(), [('row1', 'preserve')])
                    self.assertEqual(connection.execute('SELECT payload FROM libraries WHERE id="personal"').fetchone()[0], '{"private":"keep"}')
                    self.assertEqual(connection.execute('SELECT payload FROM libraries WHERE id="office-20261025"').fetchone()[0], '{"name":"base pack"}')
                    self.assertEqual(connection.execute('SELECT enabled FROM knowledge_sources WHERE id="business-source"').fetchone()[0], 0)

    def test_offline_build_reproduces_manifest_and_rejects_pinned_raw_tampering(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder) / 'office-documents'
            shutil.copytree(office_knowledge.DOCUMENT_BASE, base)
            expected = json.loads((base / 'manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(prepare_document_pack.build(base), expected)
            raw_path = base / 'raw' / expected[0]['raw_file']
            raw_path.write_bytes(raw_path.read_bytes() + b' tampered')
            with self.assertRaisesRegex(ValueError, 'Reviewed original changed'):
                prepare_document_pack.build(base)


if __name__ == '__main__':
    unittest.main()
