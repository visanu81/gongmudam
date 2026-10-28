"""Add a complete national special-leave article without replacing older evidence."""
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import urlsplit
import hashlib, json
from tools.prepare_official_pack import Tree

BASE=Path(__file__).resolve().parents[1]/'reference_data/official-20261020'
URL='https://law.go.kr/LSW/lsLinkCommonInfo.do?lsJoLnkSeq=1033978333'


def collect():
    with urlopen(Request(URL,headers={'User-Agent':'SeomuAssistant-public-source-review/1.0'}),timeout=30) as response:
        if urlsplit(response.url).hostname not in {'law.go.kr','www.law.go.kr'}:raise ValueError('Unexpected source host')
        raw=response.read(2*1024*1024+1)
    if len(raw)>2*1024*1024:raise ValueError('Source too large')
    html=raw.decode('utf-8');tree=Tree(html)
    if '2026. 10. 2.' not in tree.root.text() or '제36728호' not in tree.root.text():raise ValueError('Review the new effective version first')
    containers=[n for n in tree.root.walk() if 'lawcon' in n.attrs.get('class','').split()]
    if len(containers)!=1:raise ValueError('Unexpected article layout')
    paragraphs=[p.text() for p in containers[0].walk() if p.tag=='p' and p.text()]
    text='\n'.join(paragraphs)+'\n'
    if not text.startswith('제20조(특별휴가)') or not all(c in text for c in '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳'):
        raise ValueError('Incomplete article: all twenty paragraphs are required')
    if not all(s in text for s in ('가족돌봄휴가는 무급으로 하되','병원 진료','질병, 사고, 노령','수에 1을 더한 일수')):
        raise ValueError('Missing family-care conditions')
    digest=hashlib.sha256(text.encode('utf-8')).hexdigest()
    raw_name='national_special_full_20261024.html';name='국가공무원 복무규정_제20조_전체_v70.txt'
    manifest=BASE/'manifest.json';rows=json.loads(manifest.read_text(encoding='utf-8'))
    for path,content in ((BASE/raw_name,raw),(BASE/'excerpts'/name,text.encode('utf-8'))):
        if path.exists() and path.read_bytes()!=content:raise ValueError('Archived source differs; review instead of overwrite: '+path.name)
    old=next((r for r in rows if r['filename']==name),None)
    if old:
        if old['sha256']!=digest:raise ValueError('Archived metadata differs')
        return old
    for path,content in ((BASE/raw_name,raw),(BASE/'excerpts'/name,text.encode('utf-8'))):path.write_bytes(content)
    row=dict(title='국가공무원 복무규정',article='제20조(특별휴가)',effective_date='2026-10-02',publication='대통령령 제36728호',
        issuer='인사혁신처',institution='국가공무원',kind='법령·규정',source_url=URL,download_url=URL,
        retrieved_at=datetime.now(timezone.utc).isoformat(),raw_file=raw_name,raw_sha256=hashlib.sha256(raw).hexdigest(),
        filename=name,sha256=digest,scope='제20조 제1항~제20항 전체 · 별표·기관 지침은 별도 확인',paragraphs=len(paragraphs),collection='v70')
    rows.append(row);manifest.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return row


if __name__=='__main__':print(json.dumps(collect(),ensure_ascii=True))
