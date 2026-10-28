import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import config, folder_projects as projects, folders, project_text


class ProjectTasksTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [
            patch.object(folders, 'DB_PATH', self.root / 'folders.db'),
            patch.object(config, 'active_profile', return_value={'provider': 'offline', '_name': 'offline'}),
            patch.object(projects, 'parse_file', side_effect=lambda path, tick: project_text.extract(path)),
        ]
        for item in self.patches:
            item.start()
        folders.initialize()
        projects.initialize()
        self.app = FastAPI()
        self.app.include_router(projects.router)
        self.client = TestClient(self.app, client=('127.0.0.1', 1234), base_url='http://127.0.0.1:9988')
        self.headers = {'origin': 'http://127.0.0.1:9988'}
        self.worker = None
        self.root_files = self.root / 'source-files'
        self.root_files.mkdir()
        self.paths = {}
        self._write('교육 최초 안내.txt', '교육 최초 안내\n합성 자료\n배경 안내\n작성자: 교육담당\n교육명: 회계 실무 교육\n교육일: 2026-11-13\n장소: 3층 회의실\n회신 마감: 2026-11-06 18:00\n대상: 총무과, 회계과\n다음 할 일: 참석자 명단 제출')
        self._write('교육 변경 안내.txt', '교육 변경 안내\n합성 자료\n변경 배경\n작성자: 교육담당\n교육명: 회계 실무 교육\n교육일: 2026-11-13\n장소: 5층 대회의실\n회신 마감: 2026-11-09 17:00\n대상: 총무과, 회계과\n다음 할 일: 참석자 명단 확인')
        self._write('교육 회신 현황.txt', '교육 회신 현황\n합성 자료\n현황 배경\n작성자: 교육담당\n총무과: 2명 회신 완료\n회계과: 미회신\n다음 할 일: 11월 10일까지 중복 검토 후 최종 명단')
        self._write('물품 납품.txt', '물품 납품 안내\n프린터 구매\n납품 관련\n작성자: 구매담당\n물품: 프린터\n납품 기한: 2026-11-02\n금액: 800000원')

    def _write(self, name, text):
        path = self.root_files / name
        path.write_text(text, encoding='utf-8')
        self.paths[name] = path

    def tearDown(self):
        if self.worker:
            self.worker.stop()
        self.client.close()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def create_ready_project(self):
        r = self.client.post('/api/folder-projects', json={'name': '교육 준비'})
        self.assertEqual(r.status_code, 201, r.text)
        pid = r.json()['id']
        r = self.client.post(f'/api/folder-projects/{pid}/sources', json={
            'kind': 'folder', 'paths': [str(self.root_files)]
        }, headers=self.headers)
        self.assertEqual(r.status_code, 202, r.text)
        self.worker = projects.Worker().start()
        value = self.wait(pid, lambda v: v['jobs'] and all(j['status'] == 'completed' for j in v['jobs']))
        self.file_ids = {f['name']: f['id'] for f in value['files']}
        return pid

    def wait(self, pid, predicate, timeout=8):
        end = time.monotonic() + timeout
        value = {}
        while time.monotonic() < end:
            value = self.client.get(f'/api/folder-projects/{pid}').json()
            if predicate(value):
                return value
            time.sleep(.03)
        self.fail('대기 시간 초과: ' + json.dumps(value, ensure_ascii=False))

    def ask(self, pid, content, file_ids=None, draft=False):
        body = {'content': content, 'draft': draft}
        if file_ids is not None:
            body['file_ids'] = file_ids
        r = self.client.post(f'/api/folder-projects/{pid}/messages', json=body)
        self.assertEqual(r.status_code, 202, r.text)
        value = self.wait(pid, lambda v: v['messages'] and v['messages'][-1]['status'] == 'completed')
        answer = value['messages'][-1]
        self.assertEqual(answer['mode'], 'offline')
        return value, answer

    def assert_evidence_is_source_text(self, pid, answer):
        for evidence in answer['evidence']:
            r = self.client.get(f"/api/folder-projects/{pid}/files/{evidence['file_id']}/units/{evidence['unit']}")
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()['text'], evidence['text'])

    def test_general_summary_covers_corpus_and_every_citation_is_verifiable(self):
        pid = self.create_ready_project()
        _, answer = self.ask(pid, '이 자료들 핵심만 간단히 정리해줘')
        self.assertTrue(answer['evidence'])
        self.assertEqual({e['file_id'] for e in answer['evidence']}, set(self.file_ids.values()))
        self.assert_evidence_is_source_text(pid, answer)

    def test_topic_summary_uses_late_notice_and_excludes_unrelated_procurement(self):
        pid = self.create_ready_project()
        _, answer = self.ask(pid, '교육 자료를 요약해줘')
        self.assertIn('2026-11-09 17:00', answer['content'])
        self.assertIn('11월 10일', answer['content'])
        self.assertNotIn('800000', answer['content'])
        self.assertNotIn(self.file_ids['물품 납품.txt'], {e['file_id'] for e in answer['evidence']})
        self.assert_evidence_is_source_text(pid, answer)

    def test_question_for_dates_deadline_and_actions_stays_on_education_topic(self):
        pid = self.create_ready_project()
        _, answer = self.ask(pid, '교육 날짜와 회신 마감, 내가 해야 할 일을 정리해줘')
        for expected in ('2026-11-13', '2026-11-09 17:00', '11월 10일'):
            self.assertIn(expected, answer['content'])
        self.assertNotIn('2026-11-02', answer['content'])
        self.assert_evidence_is_source_text(pid, answer)
        _, schedule = self.ask(pid, '교육 일정과 해야할일을 알려주세요')
        for expected in ('2026-11-13', '2026-11-09 17:00', '11월 10일'):
            self.assertIn(expected, schedule['content'])
        self.assertNotIn('2026-11-02', schedule['content'])

    def test_selected_files_support_extraction_and_comparison(self):
        pid = self.create_ready_project()
        selected = [self.file_ids['교육 최초 안내.txt'], self.file_ids['교육 변경 안내.txt']]
        _, extracted = self.ask(pid, '날짜랑 해야 할 일만 뽑아줘', file_ids=selected)
        self.assertIn('2026-11-13', extracted['content'])
        self.assertIn('2026-11-06 18:00', extracted['content'])
        self.assertIn('2026-11-09 17:00', extracted['content'])
        self.assertEqual({e['file_id'] for e in extracted['evidence']}, set(selected))
        _, compared = self.ask(pid, '두 자료가 뭐가 다른지 알려줘', file_ids=selected)
        self.assertTrue(any(word in compared['content'] for word in ('차이', '다른', '변경')))
        for value in ('2026-11-06 18:00', '2026-11-09 17:00', '3층 회의실', '5층 대회의실'):
            self.assertIn(value, compared['content'])
        _, focused = self.ask(pid, '두 자료의 마감과 장소 차이를 비교해줘', file_ids=selected)
        for value in ('2026-11-06 18:00', '2026-11-09 17:00', '3층 회의실', '5층 대회의실'):
            self.assertIn(value, focused['content'])
        self.assert_evidence_is_source_text(pid, focused)

    def test_report_draft_has_known_facts_gaps_and_persists_edit(self):
        pid = self.create_ready_project()
        _, answer = self.ask(pid, '교육 준비 상황을 보고서 초안으로 써줘')
        self.assertTrue(answer['draft'])
        for expected in ('2026-11-13', '2026-11-09 17:00', '11월 10일', '[작성 필요]'):
            self.assertIn(expected, answer['content'])
        self.assertNotIn('결재 완료', answer['content'])
        self.assert_evidence_is_source_text(pid, answer)
        r = self.client.patch(f"/api/folder-projects/{pid}/messages/{answer['id']}", json={'content': '검토한 보고서 초안'})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.client.get(f'/api/folder-projects/{pid}').json()['messages'][-1]['content'], '검토한 보고서 초안')

    def test_no_evidence_and_non_draft_summary_intent(self):
        pid = self.create_ready_project()
        _, unrelated = self.ask(pid, '항공권 환불 규정을 요약해줘')
        self.assertFalse(unrelated['evidence'])
        _, summary = self.ask(pid, '이 보고서 내용을 요약해줘')
        self.assertFalse(summary['draft'])

    def test_followup_draft_keeps_explicit_two_file_scope(self):
        pid = self.create_ready_project()
        selected = [self.file_ids['교육 최초 안내.txt'], self.file_ids['교육 변경 안내.txt']]
        _, comparison = self.ask(pid, '두 자료의 마감과 장소 차이를 비교해줘', file_ids=selected)
        self.assertEqual({e['file_id'] for e in comparison['evidence']}, set(selected))
        _, draft = self.ask(pid, '그 내용으로 보고서 초안을 써줘')
        self.assertTrue(draft['draft'])
        self.assertTrue(draft['evidence'])
        self.assertEqual({e['file_id'] for e in draft['evidence']}, set(selected))
        self.assert_evidence_is_source_text(pid, draft)

    def test_comparison_identifies_missing_deadline_without_claiming_not_comparable(self):
        pid = self.create_ready_project()
        missing = self.root_files / '교육 변경 안내.txt'
        missing.write_text('교육명: 회계 실무 교육', encoding='utf-8')
        self.client.post(f'/api/folder-projects/{pid}/refresh')
        self.wait(pid, lambda v: len(v['jobs']) >= 2 and v['jobs'][-1]['status'] == 'completed')
        _, answer = self.ask(pid, '두 자료의 마감 차이를 비교해줘', file_ids=[
            self.file_ids['교육 최초 안내.txt'], self.file_ids['교육 변경 안내.txt']
        ])
        self.assertEqual({e['file_id'] for e in answer['evidence']}, {
            self.file_ids['교육 최초 안내.txt'], self.file_ids['교육 변경 안내.txt']
        })
        self.assertIn('교육 변경 안내.txt', answer['content'])
        self.assertIn('확인되지 않음', answer['content'])
        self.assertNotIn('두 개 이상', answer['content'])
        self.assertNotIn('두개이상', answer['content'])
        self.assertIn('교육명: 회계 실무 교육', next(
            e['text'] for e in answer['evidence'] if e['file_id'] == self.file_ids['교육 변경 안내.txt']
        ))
        self.assert_evidence_is_source_text(pid, answer)

    def test_education_nonresponse_query_finds_accounting_department(self):
        pid = self.create_ready_project()
        _, answer = self.ask(pid, '교육 미회신 부서를 간단히 정리해줘')
        self.assertIn('회계과', answer['content'])
        self.assertTrue(answer['evidence'])
        self.assertNotIn(self.file_ids['물품 납품.txt'], {e['file_id'] for e in answer['evidence']})

    def test_education_summary_report_prompt_is_editable_draft(self):
        pid = self.create_ready_project()
        for question in (
            '교육 자료 요약 보고서 초안을 써줘',
            '교육 자료 요약 보고서 초안을 써주세요',
            '교육 자료 요약 보고서 초안을 써 주세요',
        ):
            with self.subTest(question=question):
                _, answer = self.ask(pid, question)
                self.assertTrue(answer['draft'])
                self.assertIn('[작성 필요]', answer['content'])
                self.assertIn('2026-11-13', answer['content'])
                self.assertTrue(answer['evidence'])
                r = self.client.patch(f"/api/folder-projects/{pid}/messages/{answer['id']}", json={'content': '수정 가능'})
                self.assertEqual(r.status_code, 200, r.text)

    def test_selected_summary_keeps_multiple_dates_from_same_source_unit(self):
        pid = self.create_ready_project()
        first = self.root_files / '교육 최초 안내.txt'
        first.write_text('교육일: 2026-11-13\n후속 교육일: 2026-11-20', encoding='utf-8')
        self.client.post(f'/api/folder-projects/{pid}/refresh')
        self.wait(pid, lambda v: len(v['jobs']) >= 2 and v['jobs'][-1]['status'] == 'completed')
        _, answer = self.ask(pid, '요약해줘', file_ids=[self.file_ids['교육 최초 안내.txt']])
        self.assertIn('2026-11-13', answer['content'])
        self.assertIn('2026-11-20', answer['content'])
        self.assertNotIn('문서별로', answer['content'])
        self.assert_evidence_is_source_text(pid, answer)

    def test_freeform_report_draft_preserves_unlabeled_source_sentence(self):
        pid = self.create_ready_project()
        sentence = '참석 가능 여부는 담당 부서가 논의했습니다.'
        first = self.root_files / '교육 최초 안내.txt'
        first.write_text(sentence, encoding='utf-8')
        self.client.post(f'/api/folder-projects/{pid}/refresh')
        self.wait(pid, lambda v: len(v['jobs']) >= 2 and v['jobs'][-1]['status'] == 'completed')
        _, answer = self.ask(pid, '교육 자료로 보고서 초안을 써줘', file_ids=[self.file_ids['교육 최초 안내.txt']])
        self.assertTrue(answer['draft'])
        self.assertIn(sentence, answer['content'])
        self.assertIn('[작성 필요]', answer['content'])
        self.assertEqual({e['text'] for e in answer['evidence']}, {sentence})
        self.assert_evidence_is_source_text(pid, answer)

    def test_comparison_keeps_url_scheme_difference(self):
        self._write('HTTP 주소.txt', 'http://example.test')
        self._write('HTTPS 주소.txt', 'https://example.test')
        pid = self.create_ready_project()
        _, answer = self.ask(pid, '두 자료의 차이를 비교해줘', file_ids=[
            self.file_ids['HTTP 주소.txt'], self.file_ids['HTTPS 주소.txt']
        ])
        self.assertIn('차이', answer['content'])
        self.assertIn('http://example.test', answer['content'])
        self.assertIn('https://example.test', answer['content'])


if __name__ == '__main__':
    unittest.main()
