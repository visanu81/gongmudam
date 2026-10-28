import hashlib,json,shutil,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import service_knowledge as service,main,llm


class ServiceKnowledgeTest(unittest.TestCase):
    def test_all_ten_guides_and_twenty_six_faqs_are_hash_checked(self):
        pages,coverage,errors=service._catalog()
        self.assertEqual(errors,[]);self.assertEqual(coverage,dict(guide_pages=10,faq_questions=26))
        self.assertEqual(len({p['id'] for p in pages}),36)
        for p in pages:
            for unit in p['units']:self.assertIn(unit['text'],p['_text'])

    def test_all_faq_questions_retrieve_their_complete_answer(self):
        pages,_,_=service._catalog()
        for p in pages:
            if p['reference_kind']!='official_faq':continue
            with self.subTest(question=p['title']):
                hits=service.retrieve(p['question'])['evidence']
                matching=[h for h in hits if h['id']==p['id']]
                self.assertTrue(matching)
                self.assertIn(p['answer'],matching[0]['quote'])

    def test_each_guide_topic_and_no_unrelated_office_purchase(self):
        cases={'유연근무 시차출퇴근':'BizService10','임시공휴일이란':'BizService02',
            '영리업무 겸직 허가':'BizService06','당직 비상근무':'BizService03','국내출장이란':'BizService07',
            '공무국외출장이란':'BizService08','징계 종류':'BizService04','적극행정 징계면제 제도':'proactDisEx','공무원헌장이란':'civilCharter'}
        for q,key in cases.items():
            with self.subTest(query=q):self.assertTrue(any(h['id']==key for h in service.retrieve(q)['evidence']))
        self.assertFalse(service.retrieve('사무용품 예산 목은?')['evidence'])
        self.assertFalse(service.retrieve('지방공무원 가족돌봄휴가')['evidence'])
        self.assertFalse(service.retrieve('교원 가족돌봄휴가')['evidence'])
        self.assertFalse(service.retrieve('가족돌봄휴가',library_id='specific-library')['evidence'])

    def test_tampered_pack_is_rejected_and_never_served(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);shutil.copytree(service.BASE/service.PACKS[0],root/service.PACKS[0])
            (root/service.PACKS[0]/'BizService01.txt').write_text('변조',encoding='utf-8')
            with patch.object(service,'BASE',root),patch.object(service,'PACKS',(service.PACKS[0],)):
                self.assertFalse(service.catalog()['sources'])
                self.assertTrue(service.catalog()['problems'])
                with self.assertRaises(main.HTTPException):service.original('BizService01')

    def test_snapshot_routes_return_text_and_public_metadata_only_without_ai(self):
        client=TestClient(main.app) # no lifespan/background workers or business DBs
        with patch.object(llm,'get_provider',side_effect=AssertionError('No model')):
            listing=client.get('/api/service-guides');self.assertEqual(listing.status_code,200)
            self.assertEqual(len(listing.json()['sources']),36)
            for row in listing.json()['sources']:
                self.assertNotIn('raw_file',row);self.assertNotIn('_root',row)
                response=client.get(row['snapshot_url']);self.assertEqual(response.status_code,200)
                self.assertTrue(response.headers['content-type'].startswith('text/plain'))
                self.assertEqual(hashlib.sha256(response.content).hexdigest(),row['sha256'])
