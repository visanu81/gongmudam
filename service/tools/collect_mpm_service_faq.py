"""Archive all entries in the official MPM 복무제도 FAQ category."""
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen
import hashlib
import json
import re
import httpx
import argparse

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'reference_data' / 'mpm-faq-20261024'
HOSTS = {'www.mpm.go.kr', 'mpm.go.kr'}
LIST_URL = 'https://www.mpm.go.kr/mpm/info/hrFAQ/?boardId=bbs_0000000000000125&category=cat5&mode=list'
EXPECTED = 26
PAGE_SIZE = 15


class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children, self.parent = tag, dict(attrs), [], None

    def raw_text(self):
        if self.tag.lower() == 'img':
            return self.attrs.get('alt', '')
        return ''.join(c if isinstance(c, str) else c.raw_text() for c in self.children)

    def text(self):
        return self.raw_text()

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()


class Tree(HTMLParser):
    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
            'meta', 'param', 'source', 'track', 'wbr'}

    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        node.parent = self.stack[-1]
        self.stack[-1].children.append(node)
        if tag.lower() not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag.lower() not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag.lower() == tag.lower():
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def _fetch(url):
    if urlsplit(url).hostname not in HOSTS or not url.startswith('https://'):
        raise ValueError('Source URL is outside the official MPM host')
    # The FAQ endpoint resets this platform's urllib TLS handshake. Keep
    # certificate verification on and use the app's existing HTTP client.
    with httpx.stream('GET',url,timeout=40,follow_redirects=True,headers={'User-Agent':'SeomuAssistant-public-source-archive/1.0'}) as response:
        response.raise_for_status()
        if urlsplit(str(response.url)).hostname not in HOSTS:
            raise ValueError('Unexpected redirect host: ' + str(response.url))
        chunks=[];size=0
        for chunk in response.iter_bytes():
            size+=len(chunk)
            if size>8*1024*1024:raise ValueError('Source exceeds 8 MB')
            chunks.append(chunk)
        raw=b''.join(chunks)
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError('Source exceeds 8 MB: ' + url)
    return raw


def _clean(value):
    return re.sub(r'\s+', ' ', value).strip()


def _content(tree):
    nodes = [n for n in tree.root.walk() if 'question' in n.attrs.get('class', '').split()]
    results = []
    for node in nodes:
        question = _clean(node.text())
        answer = None
        for sibling in node.parent.children[node.parent.children.index(node) + 1:]:
            if not hasattr(sibling, 'tag'):
                continue
            if sibling.tag.lower() == 'dd' and 'answer' in sibling.attrs.get('class', '').split():
                answer = sibling
                break
            if sibling.tag.lower() == 'dt':
                break
        if answer is None:
            raise ValueError('Question has no following answer: ' + question)
        answer_text = _answer_text(answer)
        if not question or not answer_text:
            raise ValueError('Empty question or answer')
        results.append((question, answer_text, answer))
    return results


def _answer_text(answer):
    """Keep paragraph/list/table boundaries while dropping non-answer chrome."""
    pieces = []

    def visit(node):
        for child in node.children:
            if not hasattr(child, 'tag'):
                value = _clean(child)
                if value:
                    pieces.append(value)
                continue
            tag = child.tag.lower()
            if tag in {'script', 'style', 'nav', 'header', 'footer'}:
                continue
            if tag == 'table':
                for row in (n for n in child.walk() if n.tag.lower() == 'tr'):
                    cells = [_clean(cell.text()) for cell in row.children
                             if hasattr(cell, 'tag') and cell.tag.lower() in {'th', 'td'}]
                    row_text = ' | '.join(c for c in cells if c)
                    if row_text:
                        pieces.append(row_text)
            elif tag in {'p', 'li', 'br', 'div'}:
                before = len(pieces)
                if tag == 'br':
                    pieces.append('\n')
                else:
                    visit(child)
                if len(pieces) > before and pieces[-1] != '\n':
                    pieces.append('\n')
            else:
                visit(child)

    visit(answer)
    return re.sub(r' *\n+ *', '\n', ' '.join(pieces)).strip()


def _attachments(answer, page_url):
    found = []
    for node in answer.walk():
        if node.tag.lower() != 'a':
            continue
        href = node.attrs.get('href', '').strip()
        if not href or href.startswith(('javascript:', '#', 'mailto:')):
            continue
        found.append({'url': urljoin(page_url, href), 'label': _clean(node.text()), 'indexed': False})
    return list({(row['url'], row['label']): row for row in found}.values())


def _write_immutable(path, content):
    if path.exists():
        if path.read_bytes() != content:
            raise ValueError('Refusing to overwrite changed archive file: ' + str(path))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def _page_url(page_index):
    parts = urlsplit(LIST_URL)
    query = parse_qs(parts.query)
    query['pageIdx'] = [str(page_index)]
    return parts._replace(query=urlencode(query, doseq=True)).geturl()


def _display_total(tree):
    text = tree.root.raw_text()
    patterns = (r'총\s*([\d,]+)\s*건', r'전체\s*([\d,]+)\s*건', r'총\s*게시물\s*수\s*[:：]?\s*([\d,]+)')
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return int(match.group(1).replace(',', ''))
    raise ValueError('Could not determine displayed FAQ total')


def collect(base=BASE):
    base = Path(base)
    base.mkdir(parents=True, exist_ok=True)
    old_path = base / 'manifest.json'
    old = json.loads(old_path.read_text(encoding='utf-8')) if old_path.exists() else {}
    retrieved = old.get('retrieved_at') or datetime.now(timezone.utc).isoformat()
    pages = []
    list_pages = []
    questions = []
    seen = set()
    page_total = (EXPECTED + PAGE_SIZE - 1) // PAGE_SIZE
    for page_index in range(1, page_total + 1):
        list_url = _page_url(page_index)
        raw = _fetch(list_url)
        tree = Tree(raw.decode('utf-8-sig'))
        selects = [n for n in tree.root.walk() if n.tag.lower() == 'select' and n.attrs.get('name') == 'category']
        if len(selects) != 1 or not any(n.tag.lower() == 'option' and n.attrs.get('value') == 'cat5' and 'selected' in n.attrs
                                         for n in selects[0].walk()):
            raise ValueError(f'복무제도 category cat5 is not selected on page {page_index}')
        entries = _content(tree)
        if not entries:
            raise ValueError(f'No FAQ entries on page {page_index}')
        displayed_total = _display_total(tree)
        if displayed_total != EXPECTED:
            raise ValueError(f'Expected displayed FAQ total {EXPECTED}, found {displayed_total}')
        list_file = f'list-page-{page_index}.html'
        _write_immutable(base / list_file, raw)
        list_pages.append({'id': f'list-{page_index}', 'title': f'복무제도 FAQ 목록 {page_index}페이지',
                      'source_url': list_url, 'raw_file': list_file,
                      'raw_sha256': hashlib.sha256(raw).hexdigest(), 'retrieved_at': retrieved,
                      'reference_kind': 'official_faq', 'scope': '목록 HTML 원본; 개별 FAQ 본문은 각 항목 자료 참조'})
        for question, answer, answer_node in entries:
            key = hashlib.sha256(question.encode('utf-8')).hexdigest()
            if key in seen:
                raise ValueError('Duplicate question across FAQ pages: ' + question)
            seen.add(key)
            questions.append((page_index, question, answer, answer_node, list_url, raw))

    if len(questions) != EXPECTED:
        raise ValueError(f'Expected {EXPECTED} questions across {page_total} pages, found {len(questions)}')

    for ordinal, (page_index, question, answer, answer_node, list_url, raw) in enumerate(questions, 1):
        text_file = f'faq-{ordinal:02d}.txt'
        text = f'질문: {question}\n답변: {answer}\n'
        text_bytes = text.encode('utf-8')
        _write_immutable(base / text_file, text_bytes)
        answer_id = answer_node.attrs.get('id')
        source_url = list_url + (f'#{answer_id}' if answer_id else '')
        list_file = f'list-page-{page_index}.html'
        pages.append({'id': f'faq-{ordinal:02d}', 'title': question, 'source_url': source_url,
                      'raw_file': list_file, 'raw_sha256': hashlib.sha256(raw).hexdigest(),
                      'text_file': text_file, 'sha256': hashlib.sha256(text_bytes).hexdigest(),
                      'units': [{'loc': '질문/답변', 'text': text}], 'retrieved_at': retrieved,
                      'reference_kind': 'official_faq',
                      'scope': '국가공무원 FAQ 설명; 게시/개정일 미표시, 현행법령과 적용조건 별도확인',
                      'question': question, 'answer': answer,
                      'attachments': _attachments(answer_node, list_url)})

    manifest = {'format': 1, 'source': '인사혁신처 복무제도 FAQ', 'retrieved_at': retrieved,
                'coverage': {'category': 'cat5', 'expected': EXPECTED, 'pages': page_total,
                             'questions': len(questions), 'attachments': 'URL 목록만 기록/본문 미색인'},
                'list_pages': list_pages, 'pages': pages}
    encoded = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    _write_immutable(old_path, encoded)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=BASE)
    args = parser.parse_args()
    result = collect(args.output_dir)
    print(json.dumps({'questions': result['coverage']['questions'], 'pages': result['coverage']['pages'],
                      'directory': str(BASE)}, ensure_ascii=False))

