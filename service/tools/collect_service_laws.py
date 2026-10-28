"""Append reviewed national sick/public-leave and side-job articles for v70 QA."""
from pathlib import Path
from datetime import datetime,timezone
from urllib.request import Request,urlopen
from urllib.parse import urlsplit
import hashlib,json
from tools.prepare_official_pack import Tree

BASE=Path(__file__).resolve().parents[1]/'reference_data/official-20261020'
SPECS={18:('병가',('직무를 수행할 수 없을 때','연 180일','연간 6일을 초과')),
       19:('공가',('국민건강보험법','건강검진','혈액관리법','헌혈')),
       25:('영리 업무의 금지',('직무 능률을 떨어뜨리거나','다음 각 호','영리')),
       26:('겸직 허가',('사전 허가','제25조','직무 수행에 지장이 없는 경우'))}


def collect():
    rows=json.loads((BASE/'manifest.json').read_text(encoding='utf-8'));added=[]
    for number,(label,anchors) in SPECS.items():
        name=f'국가공무원 복무규정_제{number}조_전체_v70.txt';old=next((r for r in rows if r['filename']==name),None)
        if old:added.append(old);continue
        url=f'https://www.law.go.kr/LSW/lsSideInfoP.do?joNo={number:04}&joBrNo=00&lsiSeq=290349&urlMode=lsScJoRltInfoR&docCls=jo'
        with urlopen(Request(url,headers={'User-Agent':'SeomuAssistant-public-source-review/1.0'}),timeout=30) as response:
            if urlsplit(response.url).hostname not in {'law.go.kr','www.law.go.kr'}:raise ValueError('Unexpected redirect')
            raw=response.read(2*1024*1024+1)
        if len(raw)>2*1024*1024:raise ValueError('Source too large')
        tree=Tree(raw.decode('utf-8'));containers=[n for n in tree.root.walk() if 'lawcon' in n.attrs.get('class','').split()]
        if len(containers)!=1:raise ValueError('Unexpected article layout')
        paragraphs=[p.text() for p in containers[0].walk() if p.tag=='p' and p.text()]
        text='\n'.join(paragraphs)+'\n'
        if not text.startswith(f'제{number}조({label})') or not all(a in text for a in anchors):raise ValueError('Incomplete legal article: '+name)
        if '2026. 10. 2.' not in tree.root.text():raise ValueError('Unexpected effective version')
        raw_name=f'national_{number}_full_20261024.html'
        for path,content in ((BASE/raw_name,raw),(BASE/'excerpts'/name,text.encode('utf-8'))):
            if path.exists() and path.read_bytes()!=content:raise ValueError('Refusing to replace archived source')
            path.write_bytes(content)
        row=dict(title='국가공무원 복무규정',article=f'제{number}조({label})',effective_date='2026-10-02',publication='대통령령 제36728호',
            issuer='인사혁신처',institution='국가공무원',kind='법령·규정',source_url=url,download_url=url,retrieved_at=datetime.now(timezone.utc).isoformat(),
            raw_file=raw_name,raw_sha256=hashlib.sha256(raw).hexdigest(),filename=name,sha256=hashlib.sha256(text.encode('utf-8')).hexdigest(),
            scope='해당 조문 전체 · 관련 예규·기관 지침과 개별 적용조건 별도 확인',paragraphs=len(paragraphs),collection='v70')
        rows.append(row);added.append(row)
    (BASE/'manifest.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return added


if __name__=='__main__':print(json.dumps(collect(),ensure_ascii=True))
