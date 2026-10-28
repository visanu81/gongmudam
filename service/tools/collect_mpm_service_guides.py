"""Archive the reviewed MPM service-guide pages as source material."""
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen
import hashlib
import json
import re

from tools.prepare_official_pack import Tree

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'reference_data' / 'mpm-service-20261024'
HOSTS = {'www.mpm.go.kr', 'mpm.go.kr'}
PAGES = [
    ('BizService01', '공무원휴가'), ('BizService10', '유연근무'),
    ('BizService02', '공휴일'), ('BizService06', '영리업무금지및겸직'),
    ('BizService03', '당직및비상'), ('BizService07', '국내출장'),
    ('BizService08', '공무국외출장'), ('BizService04', '징계'),
    ('proactDisEx', '적극행정징계면제'), ('civilCharter', '공무원헌장'),
]
BOARD_URL = 'https://www.mpm.go.kr/mpm/info/infoService/serviceBoard/'


def _fetch(url):
    if urlsplit(url).hostname not in HOSTS or not url.startswith('https://'):
        raise ValueError('Source URL is outside the official MPM host')
    request = Request(url, headers={'User-Agent': 'SeomuAssistant-public-source-archive/1.0'})
    with urlopen(request, timeout=40) as response:
        if urlsplit(response.url).hostname not in HOSTS:
            raise ValueError('Unexpected redirect host: ' + response.url)
        raw = response.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError('Source exceeds 8 MB: ' + url)
    return raw


def _clean(text):
    return re.sub(r'\s+', ' ', text).strip()


def _content(tree):
    wrappers = [node for node in tree.root.walk()
                if node.attrs.get('id') == 'content' and 'sub' in node.attrs.get('class', '').split()]
    if len(wrappers) != 1:
        raise ValueError(f'Expected one #content.sub page wrapper, found {len(wrappers)}')
    bodies = [node for node in wrappers[0].walk()
              if 'content-body' in node.attrs.get('class', '').split()]
    if len(bodies) != 1:
        raise ValueError(f'Expected one substantive .content-body, found {len(bodies)}')
    return bodies[0]


def _units(container):
    units = []
    def visit(node, heading=''):
        for child in node.children:
            if not hasattr(child, 'tag'):
                continue
            tag = child.tag.lower()
            if tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
                heading = _clean(child.text()) or heading
                if heading:
                    units.append({'loc': heading, 'text': heading})
            elif tag == 'table':
                for row in (n for n in child.walk() if n.tag.lower() == 'tr'):
                    cells = [_clean(cell.text()) for cell in row.children
                             if hasattr(cell, 'tag') and cell.tag.lower() in ('th', 'td')]
                    value = ' | '.join(c for c in cells if c)
                    if value:
                        units.append({'loc': heading or '표', 'text': value})
            elif tag in ('p', 'li', 'dt', 'dd', 'blockquote'):
                value = _clean(child.text())
                if value:
                    units.append({'loc': heading or tag, 'text': value})
            elif tag not in ('script', 'style', 'nav', 'header', 'footer'):
                visit(child, heading)
    visit(container)
    # Break oversized prose into consecutive bounded pieces without losing text.
    bounded = []
    for unit in units:
        value = unit['text']
        while len(value) > 2000:
            split = value.rfind(' ', 0, 2000)
            if split < 1000:
                split = 2000
            bounded.append({'loc': unit['loc'], 'text': value[:split]})
            value = value[split:].lstrip()
        if value:
            bounded.append({'loc': unit['loc'], 'text': value})
    return bounded


def _attachments(container, page_url):
    results = []
    for node in container.walk():
        tag = node.tag.lower()
        if tag == 'img':
            src = node.attrs.get('src', '').strip()
            if src and not src.startswith('data:'):
                results.append({'url': urljoin(page_url, src), 'label': node.attrs.get('alt', ''),
                                'indexed': False, 'kind': 'image',
                                'note': '이미지 미다운로드·OCR 미색인'})
            continue
        if tag != 'a':
            continue
        href = node.attrs.get('href', '').strip()
        label = _clean(node.text()) or node.attrs.get('title', '').strip()
        if not href or href.startswith(('javascript:', '#', 'mailto:')):
            continue
        url = urljoin(page_url, href)
        path = urlsplit(url).path.lower()
        if re.search(r'\.(?:pdf|hwp|hwpx|docx?|xlsx?|pptx?|zip)(?:$|/)', path) or 'atchFile' in href:
            results.append({'url': url, 'label': label, 'indexed': False,
                            'kind': 'attachment', 'note': '첨부 미다운로드·미색인'})
    unique = {(item['url'], item['label'], item['kind']): item for item in results}
    return list(unique.values())


def _write_immutable(path, content):
    if path.exists():
        if path.read_bytes() != content:
            raise ValueError('Refusing to overwrite changed archive file: ' + str(path))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def collect():
    BASE.mkdir(parents=True, exist_ok=True)
    old_manifest_path = BASE / 'manifest.json'
    old_manifest = json.loads(old_manifest_path.read_text(encoding='utf-8')) if old_manifest_path.exists() else {}
    retrieved = old_manifest.get('retrieved_at') or datetime.now(timezone.utc).isoformat()
    pages = []
    for key, expected_title in PAGES:
        url = f'https://www.mpm.go.kr/mpm/info/infoService/{key}/'
        raw = _fetch(url)
        tree = Tree(raw.decode('utf-8-sig'))
        container = _content(tree)
        title_node = next((node for node in tree.root.walk() if node.tag.lower() == 'title'), None)
        title = _clean(title_node.text().split('<', 1)[0]) if title_node else expected_title
        body_text = _clean(container.text())
        # Some service pages do not repeat their heading in the body, so check the HTML title too.
        if (expected_title.replace(' ', '') not in (title + body_text).replace(' ', '')
                or len(body_text) < 80):
            raise ValueError(f'Page content missing or unexpected for {key}: {title!r}; {body_text[:100]!r}')
        units = _units(container)
        if len(units) < 2 or sum(len(u['text']) for u in units) < 80:
            raise ValueError(f'Insufficient extracted content for {key}')
        raw_name, text_name = key + '.html', key + '.txt'
        text_content = ('\n'.join(f"[{u['loc']}] {u['text']}" for u in units) + '\n').encode('utf-8')
        _write_immutable(BASE / raw_name, raw)
        _write_immutable(BASE / text_name, text_content)
        pages.append(dict(id=key, title=expected_title, source_url=url,
            raw_file=raw_name, raw_sha256=hashlib.sha256(raw).hexdigest(),
            text_file=text_name, sha256=hashlib.sha256(text_content).hexdigest(),
            units=units, retrieved_at=retrieved, reference_kind='official_service_guide',
            scope='국가공무원 제도 설명; 현행 법령 및 기관별 적용조건 별도 확인',
            attachments=_attachments(container, url)))
        print(f'{key}: {len(raw)} bytes, {len(units)} units, {sum(len(u["text"]) for u in units)} chars', flush=True)

    # Preserve the service board index only; do not follow post or attachment links.
    board_raw = _fetch(BOARD_URL)
    board_tree = Tree(board_raw.decode('utf-8-sig'))
    board_container = _content(board_tree)
    board_units = _units(board_container)
    if len(board_units) < 2 or sum(len(u['text']) for u in board_units) < 80:
        raise ValueError('Service-board list content is missing or too short')
    board_text = ('\n'.join(f"[{u['loc']}] {u['text']}" for u in board_units) + '\n').encode('utf-8')
    _write_immutable(BASE / 'serviceBoard-list.html', board_raw)
    _write_immutable(BASE / 'serviceBoard-list.txt', board_text)
    manifest = dict(format=1, source='인사혁신처 복무제도', retrieved_at=retrieved,
        coverage=dict(guide_pages=len(pages), board='목록만 보관; 과거 전체게시물과 첨부미수집',
                     attachments='링크 인벤토리만 기록; 파일은 다운로드·색인하지 않음',
                     images='원본 HTML 보관; 이미지 OCR·색인하지 않음'), pages=pages,
        board=dict(source_url=BOARD_URL, raw_file='serviceBoard-list.html',
                   raw_sha256=hashlib.sha256(board_raw).hexdigest(),
                   text_file='serviceBoard-list.txt', sha256=hashlib.sha256(board_text).hexdigest(),
                   units=board_units, retrieved_at=retrieved,
                   scope='게시판 목록 화면만; 과거 전체 게시물·첨부 미수집'))
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    _write_immutable(BASE / 'manifest.json', manifest_bytes)
    return manifest


if __name__ == '__main__':
    result = collect()
    print(json.dumps({'pages': len(result['pages']), 'board_units': len(result['board']['units']),
                      'directory': str(BASE)}, ensure_ascii=False))
