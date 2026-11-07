"""Collect the four civil-service conduct regulations article by article.

Each article is fetched from law.go.kr, checked against the expected effective
version and stored once with SHA-256 hashes. Archived files are never replaced;
a changed source must be reviewed as a new collection.
"""
from pathlib import Path
from datetime import datetime,timezone
from urllib.parse import urlsplit
import hashlib,json,re,sys,time
import httpx
from tools.prepare_official_pack import Tree

COLLECTION='service-rules-20261029'
BASE=Path(__file__).resolve().parents[1]/'reference_data'/COLLECTION
LAWS={
 'national':dict(title='국가공무원 복무규정',lsi=290349,issuer='인사혁신처',institution='국가공무원',
  version='[시행 2026. 10. 2.]',publication='대통령령 제36728호',effective_date='2026-10-02',
  articles='1 2 2-2 3 4 4-2 5 6 6-2 6-3 7 8 8-2 8-3 8-4 9 10 11 12 13 13-2 13-3 13-5 13-6 13-7 13-8 14 15 16 16-2 16-3 16-4 17 18 19 20 22 23 24 24-2 24-3 25 26 27 28 29'),
 'local':dict(title='지방공무원 복무규정',lsi=290493,issuer='행정안전부',institution='지방공무원',
  version='[시행 2026. 10. 2.]',publication='대통령령 제36728호',effective_date='2026-10-02',
  articles='1 1-2 1-3 2 2-2 2-3 2-4 2-5 2-6 3 4 4-2 4-3 5 6 7 7-2 7-3 7-4 7-5 7-6 7-7 7-8 7-9 7-10 7-11 8 9 10 11 12 13'),
 'fire':dict(title='소방공무원 복무규정',lsi=290449,issuer='소방청',institution='소방공무원',
  version='[시행 2026. 10. 2.]',publication='대통령령 제36728호',effective_date='2026-10-02',
  articles='1 2 3 4 5 6 7 8 8-2 9 9-2 10 11'),
 'police':dict(title='경찰공무원 복무규정',lsi=227157,issuer='경찰청',institution='경찰공무원',
  version='[시행 2021. 1. 5.]',publication='대통령령 제31380호',effective_date='2021-01-05',
  articles='1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20'),
 # Allowances, welfare and the national rules on duty (2nd stage: 수당·복리후생·당직).
 'national_allowance':dict(title='공무원수당 등에 관한 규정',lsi=290323,issuer='인사혁신처',institution='국가공무원',
  version='[시행 2026. 10. 2.]',publication='대통령령 제36728호',effective_date='2026-10-02',
  articles='1 2 3 4 6-2 7 7-2 10 11 11-2 11-3 12 13 14 14-2 14-3 15 16 17 17-2 18 18-3 18-5 18-6 18-7 19 20 21 22 22-2 23 23-2 24'),
 'local_allowance':dict(title='지방공무원 수당 등에 관한 규정',lsi=289957,issuer='행정안전부',institution='지방공무원',
  version='[시행 2026. 10. 1.]',publication='대통령령 제36701호',effective_date='2026-10-01',
  articles='1 2 3 5-2 6 6-2 9 10 11-2 12 13 14 14-2 15 16 17 17-2 17-3 18 18-3 18-5 18-6 18-7 18-8 19 20 21 21-2 21-3 22 23'),
 'welfare':dict(title='공무원 후생복지에 관한 규정',lsi=227215,issuer='인사혁신처',institution='공무원',
  version='[시행 2021. 1. 5.]',publication='대통령령 제31380호',effective_date='2021-01-05',
  articles='1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 17-2 18 19 20 21 21-2 21-3 21-4 22 23'),
 'national_rules':dict(title='국가공무원 복무규칙',lsi=290865,issuer='인사혁신처',institution='국가공무원',
  version='[시행 2026. 10. 2.]',publication='총리령 제2161호',effective_date='2026-10-02',
  articles='1 2 6 7 8 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39 40 41 42 43 44 45 46 47 57 58 59 60 61 62 62-2 62-3 62-4 62-5 62-6 62-7 63 64 65'),
 # Pay: the step, salary and deduction articles a 서무 officer handles; salary-system
 # chapters for diplomats, senior executives and annual-salary posts are left out.
 'national_pay':dict(title='공무원보수규정',lsi=290321,issuer='인사혁신처',institution='국가공무원',
  version='[시행 2026. 10. 2.]',publication='대통령령 제36728호',effective_date='2026-10-02',
  articles='1 2 4 5 6 7 8 9 10 11 12 13 14 15 16 18 19 19-2 20 21 22 24 25 26 27 28 29 30 30-2 30-3 31 32'),
 'local_pay':dict(title='지방공무원 보수규정',lsi=288435,issuer='행정안전부',institution='지방공무원',
  version='[시행 2026. 8. 1.]',publication='대통령령 제36548호',effective_date='2026-08-01',
  articles='1 2 3 4 5 6 8 9 9-2 10 11 12 13 14 15 17 18 18-2 19 20 21 23 24 25 26 27 28 29 29-2 29-3 30 31'),
}
# Ordinances and administrative rules are published as one page; each article is
# stored separately and keeps the hash of that single raw page.
PROVINCE_SCOPE='해당 조문 전체 · 별표·부칙·시행규칙은 별도 확인 · 시·군·구 소속은 해당 시·군·구 조례 적용'
ORDINANCES={
 'gyeonggi':dict(title='경기도 공무원 복무 조례',page='https://www.law.go.kr/LSW/ordinInfoR.do?ordinSeq=2178481',raw='gyeonggi_2178481.html',
  issuer='경기도',institution='경기도 소속 공무원',version='[시행 2026. 10. 12.]',publication='경기도조례 제8974호',effective_date='2026-10-12',
  scope='해당 조문 전체 · 별표·부칙·시행규칙은 별도 확인 · 시·군 소속은 해당 시·군 조례 적용'),
 'fire_duty':dict(title='소방공무원 당직 및 비상업무 규칙',page='https://www.law.go.kr/LSW/admRulInfoR.do?admRulSeq=2100000275662',
  raw='fire_duty_2100000275662.html',issuer='소방청',institution='소방공무원',version='소방청훈령 제456호',
  publication='2026. 3. 11.',effective_date='2026-03-11',scope='해당 조문 전체 · 별표·서식은 별도 확인 · 시·도 소방본부의 세부 기준은 별도 확인'),
 'gyeonggi_travel':dict(title='경기도 공무원 여비 조례',page='https://www.law.go.kr/LSW/ordinInfoR.do?ordinSeq=2136163',raw='gyeonggi_travel_2136163.html',
  issuer='경기도',institution='경기도 소속 공무원',version='[시행 2026. 6. 29.]',publication='경기도조례 제8887호',effective_date='2026-06-29',
  scope='해당 조문 전체 · 공무원 여비 규정을 준용(제4조 예외) · 시행규칙·도지사 기준은 별도 확인'),
 # Other provinces (2026-11-01): 광주광역시·전라남도 service ordinances were not found under their usual names.
 'seoul':dict(title='서울특별시 공무원 복무 조례',page='https://www.law.go.kr/LSW/ordinInfoR.do?ordinSeq=2147731',raw='seoul_2147731.html',
  issuer='서울특별시',institution='서울특별시 소속 공무원',version='[시행 2026. 7. 13.]',publication='서울특별시조례 제10159호',effective_date='2026-07-13',scope=PROVINCE_SCOPE),
 'busan':dict(title='부산광역시 공무원 복무 조례',page='https://www.law.go.kr/LSW/ordinInfoR.do?ordinSeq=2120461',raw='busan_2120461.html',
  issuer='부산광역시',institution='부산광역시 소속 공무원',version='[시행 2026. 4. 8.]',publication='부산광역시조례 제7920호',effective_date='2026-04-08',scope=PROVINCE_SCOPE),
 'daegu':dict(title='대구광역시 지방공무원 복무 조례',page='https://www.law.go.kr/LSW/ordinInfoR.do?ordinSeq=2079933',raw='daegu_2079933.html',
  issuer='대구광역시',institution='대구광역시 소속 공무원',version='[시행 2025. 10. 30.]',publication='대구광역시조례 제6399호',effective_date='2025-10-30',scope=PROVINCE_SCOPE),
 'incheon':dict(title='인천광역시 공무원 복무 조례',page='https://www.law.go.kr/LSW/ordinInfoR.do?ordinSeq=2177511',raw='incheon_2177511.html',
  issuer='인천광역시',institution='인천광역시 소속 공무원',version='[시행 2026. 10. 8.]',publication='인천광역시조례 제7795호',effective_date='2026-10-08',scope=PROVINCE_SCOPE),
 'daejeon':dict(title='대전광역시 지방공무원 복무 조례',page='https://www.law.go.kr/LSW/ordinInfoR.do?ordinSeq=2063591',raw='daejeon_2063591.html',
  issuer='대전광역시',institution='대전광역시 소속 공무원',version='[시행 2025. 8. 8.]',publication='대전광역시조례 제6483호',effective_date='2025-08-08',scope=PROVINCE_SCOPE),
 'ulsan':dict(title='울산광역시 공무원 복무 조례',page='https://www.law.go.kr/LSW/ordinInfoR.do?ordinSeq=2026977',raw='ulsan_2026977.html',
  issuer='울산광역시',institution='울산광역시 소속 공무원',version='[시행 2025. 4. 3.]',publication='울산광역시조례 제3082호',effective_date='2025-04-03',scope=PROVINCE_SCOPE),
 'sejong':dict(title='세종특별자치시 지방공무원 복무 조례',page='https://www.law.go.kr/LSW/ordinInfoR.do?ordinSeq=2113497',raw='sejong_2113497.html',
  issuer='세종특별자치시',institution='세종특별자치시 소속 공무원',version='[시행 2026. 2. 27.]',publication='세종특별자치시조례 제2984호',effective_date='2026-02-27',scope=PROVINCE_SCOPE),
 'gangwon':dict(title='강원특별자치도 공무원 복무 조례',page='https://www.law.go.kr/LSW/ordinInfoR.do?ordinSeq=2083281',raw='gangwon_2083281.html',
  issuer='강원특별자치도',institution='강원특별자치도 소속 공무원',version='[시행 2025. 11. 7.]',publication='강원특별자치도조례 제5696호',effective_date='2025-11-07',scope=PROVINCE_SCOPE),
 'chungbuk':dict(title='충청북도 지방공무원 복무 조례',page='https://www.law.go.kr/LSW/ordinInfoR.do?ordinSeq=2143389',raw='chungbuk_2143389.html',
  issuer='충청북도',institution='충청북도 소속 공무원',version='[시행 2026. 7. 3.]',publication='충청북도조례 제5592호',effective_date='2026-07-03',scope=PROVINCE_SCOPE),
 'chungnam':dict(title='충청남도 공무원 복무 조례',page='https://www.law.go.kr/LSW/ordinInfoR.do?ordinSeq=2074361',raw='chungnam_2074361.html',
  issuer='충청남도',institution='충청남도 소속 공무원',version='[시행 2025. 9. 30.]',publication='충청남도조례 제5987호',effective_date='2025-09-30',scope=PROVINCE_SCOPE),
 'jeonbuk':dict(title='전북특별자치도 지방공무원 복무조례',page='https://www.law.go.kr/LSW/ordinInfoR.do?ordinSeq=2078317',raw='jeonbuk_2078317.html',
  issuer='전북특별자치도',institution='전북특별자치도 소속 공무원',version='[시행 2025. 10. 10.]',publication='전북특별자치도조례 제5882호',effective_date='2025-10-10',scope=PROVINCE_SCOPE),
 'gyeongbuk':dict(title='경상북도 공무원 복무 조례',page='https://www.law.go.kr/LSW/ordinInfoR.do?ordinSeq=2057005',raw='gyeongbuk_2057005.html',
  issuer='경상북도',institution='경상북도 소속 공무원',version='[시행 2025. 7. 14.]',publication='경상북도조례 제5302호',effective_date='2025-07-14',scope=PROVINCE_SCOPE),
 'gyeongnam':dict(title='경상남도 지방공무원 복무 조례',page='https://www.law.go.kr/LSW/ordinInfoR.do?ordinSeq=2127133',raw='gyeongnam_2127133.html',
  issuer='경상남도',institution='경상남도 소속 공무원',version='[시행 2026. 4. 30.]',publication='경상남도조례 제6069호',effective_date='2026-04-30',scope=PROVINCE_SCOPE),
 'jeju':dict(title='제주특별자치도 공무원 복무 조례',page='https://www.law.go.kr/LSW/ordinInfoR.do?ordinSeq=2158643',raw='jeju_2158643.html',
  issuer='제주특별자치도',institution='제주특별자치도 소속 공무원',version='[시행 2026. 8. 7.]',publication='제주특별자치도조례 제4351호',effective_date='2026-08-07',scope=PROVINCE_SCOPE),
}
# Navigation tags only; an answer still needs the stored article text.
TOPICS=(('leave',r'휴가|연가|병가|공가|휴무|포상휴가'),('hours',r'근무시간|시간외|현업|교대제|근무혁신|연일근무'),
        ('duty',r'당직|비상|소집'),('travel',r'출장|여행'),('sidejob',r'영리|겸직'),('politics',r'정치'),
        ('conduct',r'선서|책임|기강|친절|비밀|복장|용모|예절|자세|강령|일상행동|음주|수칙|안전사고'),('dispatch',r'파견|겸임|해직|면직'))
MAX_BYTES=2*1024*1024


def label(article):
    main,_,branch=article.partition('-')
    return f'제{main}조'+(f'의{branch}' if branch else '')


def url(lsi,article):
    main,_,branch=article.partition('-')
    return f'https://www.law.go.kr/LSW/lsSideInfoP.do?joNo={int(main):04}&joBrNo={int(branch or 0):02}&lsiSeq={lsi}&urlMode=lsScJoRltInfoR&docCls=jo'


def fetch(address,attempts=4):
    for attempt in range(attempts):
        try:
            response=httpx.get(address,headers={'User-Agent':'SeomuAssistant-public-source-review/1.0'},timeout=60,follow_redirects=True)
            response.raise_for_status()
            if urlsplit(str(response.url)).hostname not in {'law.go.kr','www.law.go.kr'}:raise ValueError('Unexpected redirect')
            raw=response.content
            break
        except (TimeoutError,OSError,httpx.HTTPError):
            if attempt==attempts-1:raise
            time.sleep(5*(attempt+1))
    if len(raw)>MAX_BYTES:raise ValueError('Source too large')
    return raw


def article_text(raw,law,article):
    tree=Tree(raw.decode('utf-8'));page=tree.root.text()
    if law['version'] not in page or law['publication'] not in page:raise ValueError('Unexpected effective version: '+law['title']+' '+article)
    containers=[n for n in tree.root.walk() if 'lawcon' in n.attrs.get('class','').split()]
    if len(containers)!=1:raise ValueError('Unexpected article layout: '+law['title']+' '+article)
    paragraphs=[p.text() for p in containers[0].walk() if p.tag=='p' and p.text()]
    heading=re.match(re.escape(label(article))+r'\(([^)]{1,80})\)',paragraphs[0] if paragraphs else '')
    if not heading:raise ValueError('Article heading differs: '+law['title']+' '+article)
    return paragraphs,heading[1]


def keep(path,content):
    if path.exists() and path.read_bytes()!=content:raise ValueError('Refusing to replace archived source: '+path.name)
    path.write_bytes(content)


def collect(keys=None,delay=0.5):
    (BASE/'raw').mkdir(parents=True,exist_ok=True);(BASE/'excerpts').mkdir(exist_ok=True)
    manifest=BASE/'manifest.json'
    rows={r['id']:r for r in json.loads(manifest.read_text(encoding='utf-8'))} if manifest.exists() else {}
    for key,law in LAWS.items():
        if keys and key not in keys:continue
        for article in law['articles'].split():
            rid=f'{key}-{article}'
            if rid in rows:continue
            address=url(law['lsi'],article);raw=fetch(address)
            paragraphs,name=article_text(raw,law,article)
            text='\n'.join(paragraphs)+'\n'
            raw_name=f'{key}_{article}.html';filename=f"{law['title']}_{label(article)}.txt"
            keep(BASE/'raw'/raw_name,raw);keep(BASE/'excerpts'/filename,text.encode('utf-8'))
            topics=[t for t,pattern in TOPICS if re.search(pattern,name)]
            rows[rid]=dict(id=rid,collection=COLLECTION,law=key,title=law['title'],article=f'{label(article)}({name})',
                article_label=label(article),article_name=name,topics=topics,applies_to=[key],
                effective_date=law['effective_date'],publication=law['publication'],issuer=law['issuer'],institution=law['institution'],
                kind='법령·규정',source_url=address,download_url=address,retrieved_at=datetime.now(timezone.utc).isoformat(),
                raw_file=raw_name,raw_sha256=hashlib.sha256(raw).hexdigest(),filename=filename,
                sha256=hashlib.sha256(text.encode('utf-8')).hexdigest(),paragraphs=len(paragraphs),
                scope='해당 조문 전체 · 별표·부칙·관련 예규·기관 지침은 별도 확인')
            manifest.write_text(json.dumps(list(rows.values()),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            time.sleep(delay)
    return list(rows.values())


def collect_ordinance(key):
    law=ORDINANCES[key];manifest=BASE/'manifest.json'
    rows={r['id']:r for r in json.loads(manifest.read_text(encoding='utf-8'))}
    address=law['page']
    raw=fetch(address);tree=Tree(raw.decode('utf-8'))
    if law['version'] not in tree.root.text() or law['publication'] not in tree.root.text():
        raise ValueError('Unexpected effective version: '+law['title'])
    raw_name=law['raw'];keep(BASE/'raw'/raw_name,raw)
    for container in [n for n in tree.root.walk() if 'lawcon' in n.attrs.get('class','').split()]:
        paragraphs=[p.text() for p in container.walk() if p.tag=='p' and p.text()]
        first=paragraphs[0] if paragraphs else ''
        heading=re.match(r'제(\d+)조(?:의(\d+))?\s?\(([^)]{1,80})\)',first)
        # A repealed article ("제8조 삭제", "제11조 ① 삭제", "제16조의2 (제목) <삭제 ...>") has no text to store.
        if re.match(r'제\d+조(?:의\d+)?\s*(?:①\s*)?<?\s*삭제',first) or heading and re.match(r'\s*<\s*삭제',first[heading.end():]):continue
        if not heading:raise ValueError('Article heading differs: '+law['title'])
        article=heading[1]+(f'-{heading[2]}' if heading[2] else '');name=heading[3]
        text='\n'.join(paragraphs)+'\n';filename=f"{law['title']}_{label(article)}.txt"
        keep(BASE/'excerpts'/filename,text.encode('utf-8'))
        rows[f'{key}-{article}']=dict(id=f'{key}-{article}',collection=COLLECTION,law=key,title=law['title'],
            article=f'{label(article)}({name})',article_label=label(article),article_name=name,
            topics=[t for t,pattern in TOPICS if re.search(pattern,name)],applies_to=[key],
            effective_date=law['effective_date'],publication=law['publication'],issuer=law['issuer'],institution=law['institution'],
            kind='법령·규정',source_url=address,download_url=address,retrieved_at=datetime.now(timezone.utc).isoformat(),
            raw_file=raw_name,raw_sha256=hashlib.sha256(raw).hexdigest(),filename=filename,
            sha256=hashlib.sha256(text.encode('utf-8')).hexdigest(),paragraphs=len(paragraphs),
            scope=law['scope'])
    manifest.write_text(json.dumps(list(rows.values()),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return list(rows.values())


if __name__=='__main__':
    keys=set(sys.argv[1:])
    pages=keys & set(ORDINANCES)
    result=[collect_ordinance(key) for key in sorted(pages)][-1] if pages and pages==keys else collect(keys or None)
    print(json.dumps({k:sum(r['law']==k for r in result) for k in (*LAWS,*ORDINANCES)},ensure_ascii=True))
