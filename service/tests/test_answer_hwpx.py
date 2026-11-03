"""An answer record saved as TXT can also be saved as a 한글(HWPX) document."""
from pathlib import Path
from urllib.parse import unquote
import tempfile, unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import project_export, project_text


class AnswerHwpxTest(unittest.TestCase):
    def setUp(self):
        app = FastAPI(); app.include_router(project_export.router)
        self.client = TestClient(app)
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)

    def test_record_text_reads_back_from_the_hwpx(self):
        record = '서무비서 답변 확인 기록\n\n질문 원문\n연가는 며칠이야?\n\n출처 및 인용 원문\n [근거 1]\n제목: 복무 규정\n인용 원문:\n연가 일수 원문'
        r = self.client.post('/api/exports/hwpx', json=dict(title='서무비서 답변 · 연가는 며칠이야?', text=record,
                                                            filename='seomu-answer-20261103.hwpx'))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.headers['content-type'], 'application/hwp+zip')
        self.assertEqual(unquote(r.headers['content-disposition'].split("''")[1]), 'seomu-answer-20261103.hwpx')
        out = Path(self.temp.name) / '답변.hwpx'; out.write_bytes(r.content)
        texts = [u['text'] for u in project_text.extract(out)['units']]
        self.assertIn('서무비서 답변 · 연가는 며칠이야?', texts)
        self.assertIn('연가는 며칠이야?', texts)
        self.assertIn('제목: 복무 규정', texts)
        self.assertIn('연가 일수 원문', texts)

    def test_filename_cannot_leave_the_download_and_size_is_limited(self):
        r = self.client.post('/api/exports/hwpx', json=dict(title='답변', text='본문', filename='../../a:b'))
        self.assertEqual(unquote(r.headers['content-disposition'].split("''")[1]), '_.._a_b.hwpx')
        self.assertEqual(self.client.post('/api/exports/hwpx', json=dict(title='답변', text='가' * 200_001)).status_code, 422)
        self.assertEqual(self.client.post('/api/exports/hwpx', json=dict(title='', text='본문')).status_code, 422)


if __name__ == '__main__':
    unittest.main()
