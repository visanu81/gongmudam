"""Office-pack retrieval, citation, and add-only registration regressions."""
import os
import json
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import knowledge, llm, main, office_knowledge
from tools import register_office_pack


ROOT = Path(__file__).resolve().parents[1]


class OfficeKnowledgeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((office_knowledge.BASE / 'manifest.json').read_text(encoding='utf-8'))
        cls.sources = [dict(
            id=row['id'], title=row['title'] + ' ' + row['article'], enabled=True,
            current=True, sha256=row['sha256'], effective_date=row['effective_date'],
            kind=row['kind'], institution=row['institution'], limited=False,
            library_id='office-test', file_id=row['id'], units=row['units'], official=row,
        ) for row in cls.manifest]

    def ask(self, query, sources=None, *, use_ai=False):
        with patch.object(knowledge, 'sources', return_value=self.sources if sources is None else sources), \
                patch.object(knowledge.config, 'active_profile', return_value={'provider': 'offline'}), \
                patch.object(knowledge, '_experience_hits', return_value=[]), \
                patch.object(llm, 'get_provider', side_effect=AssertionError('Unexpected AI provider lookup')):
            return main.api_ask(dict(query=query, guidance=True, use_ai=use_ai, today='2026-10-25'))

    def assert_office_summary(self, result):
        self.assertFalse(result['guidance']['ai_used'])
        knowledge_reply = result['knowledge']
        self.assertFalse(knowledge_reply.get('model'))
        self.assertEqual(knowledge_reply['mode'], 'source_search')
        self.assertIsNone(result['model'])
        self.assertTrue(knowledge_reply['evidence'])
        summary = knowledge_reply['tree']
        self.assertEqual(summary['kind'], 'summary')
        self.assertIn('근거', result['answer'])
        for branch in summary['branches']:
            for item in branch['items']:
                self.assertTrue(item['support_quotes'])
                hit = knowledge_reply['evidence'][item['ref'] - 1]
                for quote in item['support_quotes']:
                    self.assertIn(quote, hit['text'])

    def test_reviewed_office_questions_have_complete_supported_summaries(self):
        queries = (
            '교육 참석자 명단에 전화번호도 받아도 되나요?',
            '교육 참석자 명단을 다른 기관에 보내도 되나요?',
            '교육이 끝났는데 개인정보 명단을 바로 삭제해도 되나요?',
            '주민등록번호는 동의만 받으면 수집해도 되나요?',
            '개인정보가 담긴 명단을 잘못 보냈어요',
            '이메일로 받은 업무자료도 기록물로 등록해야 하나요?',
            '보존기간이 지난 기록물을 제가 지워도 되나요?',
            '모든 회의는 회의록을 작성해야 하나요?',
            '기록물은 몇 년 보관해야 하나요?',
            '정보공개 청구는 며칠 안에 답해야 하나요?',
            '다른 기관 자료에 대한 정보공개 청구가 왔어요',
            '정보공개 자료에 개인정보가 섞였는데 전부 비공개해야 하나요?',
            '정보공개 이의신청 처리기한은?',
            '후임자에게 업무 인수인계를 어떻게 해야 하나요?',
            '업무편람은 한 번 만들면 끝인가요?',
        )
        for query in queries:
            with self.subTest(query=query):
                self.assert_office_summary(self.ask(query))

    def test_unsupported_out_of_scope_and_future_queries_have_no_evidence(self):
        queries = (
            '개인정보 유출 과태료는 얼마인가요?',
            '공공기관 업무 인수인계 방법은?',
            '2027년 정보공개 청구 처리기한은?',
            '2020-01-01 개인정보 수집 기준은?',
            '2020년 개인정보 수집 기준은?',
            '2020년 정보공개 이의신청 처리기한은?',
            '개인정보 열람청구를 거부할 수 있나요?',
            '만 14세 미만 아동의 개인정보는 아이 동의만 받아도 되나요?',
            '정보공개 수수료 면제 기준은?',
            '반복청구한 정보공개를 종결해도 되나요?',
        )
        for query in queries:
            with self.subTest(query=query):
                self.assertFalse(self.ask(query)['knowledge']['evidence'])

    def test_special_procedures_use_their_own_rules_instead_of_generic_defaults(self):
        cases = (
            ('민감정보인 병력과 건강정보는 동의 없이 수집해도 되나요?', 'office-privacy-art23'),
            ('정보공개 제3자 이의신청 기한은?', 'office-disclosure-21'),
            ('보존기간이 지난 기록물을 제가 지워도 되나요?', 'office-public-records-27'),
        )
        for query, sid in cases:
            result = self.ask(query)
            self.assert_office_summary(result)
            self.assertIn(sid, {h['official']['id'] for h in result['knowledge']['evidence']})

    def test_ui_registration_uuid_keeps_canonical_article_identity(self):
        sources=[row|{'id':'registered-'+str(i),'file_id':'file-'+str(i)} for i,row in enumerate(self.sources)]
        result=self.ask('개인정보 명단을 외부에 제공해도 되나요?',sources)
        self.assert_office_summary(result)
        self.assertTrue(all(h['source_id'].startswith('registered-') for h in result['knowledge']['evidence']))

    def test_compound_questions_keep_all_distinct_required_procedures(self):
        for query, ids in (
            ('건강정보와 주민등록번호를 별도 동의만 받고 수집해도 되나요?', {'office-privacy-art23','office-privacy-art24-2'}),
            ('민감정보인 병력을 다른 기관에 보내도 되나요?', {'office-privacy-art23','office-privacy-art17','office-privacy-art18'}),
            ('정보공개 개인정보가 섞인 자료 공개 여부 결정 기한은?', {'office-disclosure-9','office-disclosure-14','office-disclosure-11','office-disclosure-13'}),
        ):
            result=self.ask(query)
            self.assert_office_summary(result)
            self.assertTrue(ids <= {h['official']['id'] for h in result['knowledge']['evidence']})

    def test_non_guidance_api_also_honors_explicit_ai_off(self):
        with patch.object(knowledge,'sources',return_value=self.sources), \
                patch.object(knowledge.config,'active_profile',return_value={'provider':'offline'}), \
                patch.object(knowledge,'_experience_hits',return_value=[]), \
                patch.object(llm,'get_provider',side_effect=AssertionError('AI off must not construct a provider')):
            result=main.api_ask(dict(query='정보공개 청구 처리기한은?',use_ai=False,today='2026-10-25'))
        self.assertEqual(result['knowledge']['tree']['kind'],'summary')
        self.assertIn('10일',result['answer'])

    def test_missing_or_invalid_required_office_source_removes_entire_answer(self):
        query = '정보공개 청구는 며칠 안에 답해야 하나요?'
        source = next(row for row in self.sources if row['id'] in {
            sid for item in office_knowledge.load('questions.json')
            if item['id'] == 'disclosure-deadline' for sid in item['sources']
        })
        unavailable = [row for row in self.sources if row['id'] != source['id']]
        self.assertFalse(self.ask(query, unavailable)['knowledge']['evidence'])
        for field in ('enabled', 'current'):
            disabled = [dict(row) for row in self.sources]
            next(row for row in disabled if row['id'] == source['id'])[field] = False
            with self.subTest(field=field):
                self.assertFalse(self.ask(query, disabled)['knowledge']['evidence'])
        with patch.object(office_knowledge, 'metadata', return_value=None):
            self.assertFalse(self.ask(query)['knowledge']['evidence'])

    def test_office_pack_does_not_answer_unrelated_query(self):
        for query in ('출장정산 방법을 알려줘', '야근식비 지급 기준은?'):
            with self.subTest(query=query):
                self.assertFalse(self.ask(query)['knowledge']['evidence'])

    def test_ai_provider_failure_returns_same_reviewed_summary_as_ai_off(self):
        query = '교육 참석자 명단에 전화번호도 받아도 되나요?'
        baseline = self.ask(query)

        class BrokenLocalProvider:
            available = True

            def chat(self, *args, **kwargs):
                raise llm.LLMError('local model unavailable')

        with patch.object(knowledge, 'sources', return_value=self.sources), \
                patch.object(knowledge.config, 'active_profile', return_value={
                    'provider': 'local', 'base_url': 'http://127.0.0.1:1234', 'model': 'test',
                }), \
                patch.object(knowledge, '_experience_hits', return_value=[]), \
                patch.object(llm, 'get_provider', return_value=BrokenLocalProvider()):
            result = main.api_ask(dict(query=query, guidance=True, use_ai=True, today='2026-10-25'))
        self.assertEqual(result['knowledge']['answer'], baseline['knowledge']['answer'])
        self.assertEqual(result['knowledge']['evidence'], baseline['knowledge']['evidence'])
        self.assert_office_summary(result)

    def test_original_endpoint_returns_verified_plain_text_and_rejects_unknown_hash(self):
        client = TestClient(main.app)
        source = self.manifest[0]
        ok = client.get(f"/api/office-sources/{source['sha256']}/original")
        self.assertEqual(ok.status_code, 200)
        self.assertTrue(ok.headers['content-type'].startswith('text/plain'))
        self.assertIn(source['title'], ok.text)
        missing = client.get('/api/office-sources/' + 'f' * 64 + '/original')
        self.assertEqual(missing.status_code, 404)

    def make_temp_pack(self, parent):
        target = parent / 'office-pack'
        shutil.copytree(office_knowledge.BASE, target)
        return target

    def make_db(self, path):
        with closing(sqlite3.connect(path)) as connection:
            connection.execute('CREATE TABLE libraries(id TEXT PRIMARY KEY,version INTEGER,payload TEXT)')
            connection.execute('CREATE TABLE knowledge_sources(id TEXT PRIMARY KEY,library_id TEXT,file_id TEXT,enabled INTEGER,payload TEXT,UNIQUE(library_id,file_id))')
            connection.execute('CREATE TABLE business_rows(id TEXT PRIMARY KEY,value TEXT)')
            connection.execute('INSERT INTO libraries VALUES(?,?,?)', ('personal', 3, '{"private":"keep"}'))
            connection.execute('INSERT INTO knowledge_sources VALUES(?,?,?,?,?)',
                               ('business-source', 'personal', 'business-file', 0, '{"sha256":"existing"}'))
            connection.execute('INSERT INTO business_rows VALUES(?,?)', ('row1', 'preserve'))
            connection.commit()

    def test_registration_dry_run_apply_and_idempotency_preserve_existing_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pack = self.make_temp_pack(root)
            db = root / 'folders.db'
            self.make_db(db)
            with patch.object(office_knowledge, 'BASE', pack):
                dry = register_office_pack.register(db)
                self.assertEqual(len(dry['would_add']), len(self.manifest))
                self.assertEqual(dry['added'], [])
                with closing(sqlite3.connect(db)) as connection:
                    self.assertEqual(connection.execute('SELECT COUNT(*) FROM knowledge_sources').fetchone()[0], 1)
                applied = register_office_pack.register(db, apply=True)
                self.assertEqual(len(applied['added']), len(self.manifest))
                again = register_office_pack.register(db, apply=True)
                self.assertEqual(again['would_add'], [])
                self.assertEqual(again['added'], [])
                with closing(sqlite3.connect(db)) as connection:
                    self.assertEqual(connection.execute('SELECT COUNT(*) FROM knowledge_sources').fetchone()[0], len(self.manifest) + 1)
                    self.assertEqual(connection.execute('SELECT * FROM business_rows').fetchall(), [('row1', 'preserve')])
                    self.assertEqual(connection.execute('SELECT payload FROM libraries WHERE id="personal"').fetchone()[0], '{"private":"keep"}')
                    self.assertEqual(connection.execute('SELECT enabled FROM knowledge_sources WHERE id="business-source"').fetchone()[0], 0)

    def test_registration_stores_absolute_paths_for_a_relative_base(self):
        # A relative path would make every registered source read as changed once the app starts elsewhere.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pack = self.make_temp_pack(root)
            db = root / 'folders.db'
            self.make_db(db)
            before = os.getcwd()
            os.chdir(root)
            try:
                with patch.object(office_knowledge, 'BASE', pack):
                    register_office_pack.register(db, apply=True, base=Path(pack.name))
            finally:
                os.chdir(before)
            with closing(sqlite3.connect(db)) as connection:
                payloads = connection.execute('SELECT payload FROM knowledge_sources WHERE id != "business-source"').fetchall()
            self.assertEqual(len(payloads), len(self.manifest))
            for (payload,) in payloads:
                self.assertTrue(Path(json.loads(payload)['path']).is_absolute())

    def test_registration_rejects_tampered_source_metadata_without_database_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pack = self.make_temp_pack(root)
            db = root / 'folders.db'
            self.make_db(db)
            manifest_path = pack / 'manifest.json'
            rows = json.loads(manifest_path.read_text(encoding='utf-8'))
            rows[0]['sha256'] = '0' * 64
            manifest_path.write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
            with patch.object(office_knowledge, 'BASE', pack):
                with self.assertRaisesRegex(ValueError, 'validation failed'):
                    register_office_pack.register(db, apply=True)
            with closing(sqlite3.connect(db)) as connection:
                self.assertEqual(connection.execute('SELECT COUNT(*) FROM knowledge_sources').fetchone()[0], 1)
                self.assertEqual(connection.execute('SELECT * FROM business_rows').fetchall(), [('row1', 'preserve')])


if __name__ == '__main__':
    unittest.main()
