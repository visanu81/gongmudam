"""Save outputs and answer records as 한글(HWPX) documents.

The output's own text comes first, then the sources it cites, so the file can
be edited in 한글 and still shows where each fact came from.
"""
import re
from urllib.parse import quote

from fastapi import APIRouter, Response
from hwpx import HwpxDocument
from pydantic import BaseModel, Field

router = APIRouter(prefix='/api/exports', tags=['한글 저장'])


def hwpx(title, text, evidence):
    """HWPX bytes: a heading, the output text line by line, then the cited sources."""
    doc = HwpxDocument.new()
    doc.add_heading(title, level=1)
    for line in text.replace('\r\n', '\n').split('\n'):
        doc.add_paragraph(line)
    if evidence:
        doc.add_paragraph('')
        doc.add_heading('근거 자료', level=2)
        for n, e in enumerate(evidence, 1):
            doc.add_paragraph(f"[{e.get('ref', n)}] {e.get('name', '')} · {e.get('loc', '')}")
    return doc.to_bytes()


class Record(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    # The browser's answer record (질문·요약·원문·출처) already lists its sources.
    text: str = Field(min_length=1, max_length=200_000)
    filename: str = Field(default='', max_length=120)


@router.post('/hwpx')
def record_hwpx(body: Record):
    """The answer record the browser saves as TXT, as a 한글 document instead."""
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', body.filename).strip(' .') or '서무비서-답변'
    if not name.lower().endswith('.hwpx'):
        name += '.hwpx'
    return Response(hwpx(body.title, body.text, []), media_type='application/hwp+zip',
                    headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(name)}"})
