"""업무자료 정리 결과물을 한글(HWPX) 문서로 내려받기.

The output's own text comes first, then the sources it cites, so the file can
be edited in 한글 and still shows where each fact came from.
"""
from hwpx import HwpxDocument


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
