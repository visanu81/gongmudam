"""Build immutable, fully cited sections from two reviewed official originals."""
from pathlib import Path
from datetime import datetime,timezone
import argparse
import hashlib
import json
import shutil
import re

from app import project_text
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parents[1]
NATIONAL_SHA='7ae70437d4aee67c74df4acf619643f2a10a80bc0d7b088523bd382a003b034f'
LOCAL_SHA='b80bb9653ddf79cdab93148510884f35e5e6a402ac6af8d0e6e2fe4f764ba7ca'


def save(path,data):
    if path.exists() and path.read_bytes()!=data:raise ValueError('Preserve previous source: '+str(path))
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(data)


def clip(text,start=None,end=None):
    compact=[];positions=[]
    for i,c in enumerate(text):
        if not c.isspace():compact.append(c);positions.append(i)
    flat=''.join(compact);a=0;b=len(text)
    if start:
        at=flat.index(re.sub(r'\s+','',start));a=positions[at]
    if end:
        at=flat.index(re.sub(r'\s+','',end),next((i for i,p in enumerate(positions) if p>=a),0));b=positions[at]
    if b<=a:raise ValueError('Invalid section boundaries')
    return text[a:b].strip()


def build(national,local,destination):
    national=Path(national);local=Path(local);dest=Path(destination)
    for path,sha in ((national,NATIONAL_SHA),(local,LOCAL_SHA)):
        if hashlib.sha256(path.read_bytes()).hexdigest()!=sha:raise ValueError('Review a changed official original before building')
    n=project_text.extract(national)
    if n['status']!='ready':raise ValueError('National original was not fully extracted')
    pages=[dict(page=i,loc=f'PDF {i}쪽',text=p.extract_text() or '') for i,p in enumerate(PdfReader(local).pages,1)]
    if len(pages)!=222 or '제446호' not in pages[0]['text'].replace(' ',''):raise ValueError('Unexpected local edition')
    save(dest/'raw/national-budget-2026.hwpx',national.read_bytes())
    save(dest/'raw/local-accounting-446.pdf',local.read_bytes())
    save(dest/'national-full-text.json',json.dumps(n,ensure_ascii=False,indent=2).encode('utf-8'))
    save(dest/'local-full-text.json',json.dumps(pages,ensure_ascii=False,indent=2).encode('utf-8'))
    manifest=[]
    def section(key,article,topics,units,scope):
        if not units or not all(u['text'].strip() for u in units):raise ValueError('Empty section')
        text='\n'.join(u['text'] for u in units)+'\n';sha=hashlib.sha256(text.encode()).hexdigest()
        filename=key+'.txt';save(dest/'excerpts'/filename,text.encode('utf-8'))
        islocal=scope=='local_government'
        loc=' / '.join(u['loc'] for u in units)
        data=dict(id='finance-'+key,title='지방자치단체 회계관리에 관한 훈령' if islocal else '2026년도 예산 및 기금운용계획 집행지침',
            article=article,filename=filename,sha256=sha,kind='기관 지침',
            issuer='행정안전부' if islocal else '기획예산처',institution='지방자치단체 · 2026년도 회계' if islocal else '국가기관 · 2026년도 예산·기금',
            effective_date='2026-07-06' if islocal else '',fiscal_years=[2026],finance_scope=scope,finance_topics=topics,
            source_url='https://www.law.go.kr/LSW/admRulLsInfoP.do?admRulSeq=2100000281370' if islocal else 'https://mpb.go.kr/web/main/bbs/b_0009/1157',
            download_url='https://www.law.go.kr/LSW/flDownload.do?flSeq=166472455' if islocal else 'https://mpb.go.kr/web/main/file/download/uu/a0cfe2b242d047759bd51c958eabc9bb',
            raw_file='local-accounting-446.pdf' if islocal else 'national-budget-2026.hwpx',raw_sha256=LOCAL_SHA if islocal else NATIONAL_SHA,
            publication='행정안전부훈령 제446호 · 2026-06-28' if islocal else '2026년도 집행지침 · 공식 지침 게시 2026-01-12',
            retrieved_at='2026-10-25',collection='finance-20261025',scope='2026년도 '+('지방자치단체' if islocal else '국가')+' 회계 기준. 관련 조례·기관 지급기준·준용 별표와 개별 적용조건은 함께 확인. 원문 '+loc,
            units=[dict(loc=loc,text=text.rstrip('\n'))])
        if islocal:
            data['pdf_pages']=[u['page'] for u in units]
            data['download_url']+='#page='+str(data['pdf_pages'][0])
        manifest.append(data)
    def nu(section_num,start,end):
        selected=[]
        for u in n['units']:
            m=re.fullmatch(r'(\d+)구역 (\d+)문단',u['loc'])
            if m and int(m[1])==section_num and start<=int(m[2])<=end:selected.append(u)
        if not selected:raise ValueError('Missing HWPX section')
        return [dict(loc=f'HWPX {section_num}구역 {start}~{end}문단',text='\n'.join(u['text'] for u in selected))]
    ns='national_government';ls='local_government'
    section('national-2026-supplies','Ⅲ 1-1. 일반수용비(210-01목)',['office_supplies'],nu(3,2572,2614),ns)
    section('national-2026-overtime-meals','Ⅲ 1-5. 특근매식비(210-05목)',['overtime_meal'],nu(3,2660,2682),ns)
    section('national-2026-meetings','Ⅲ 4. 업무추진비 공통지침 및 4-1·4-2. 사업추진비·관서업무추진비',['meeting_meal'],nu(3,3071,3191),ns)
    section('national-2026-lecturers','Ⅱ 6. 공무원교육훈련기관 및 교육훈련비 예산',['lecturer','manuscript'],nu(3,1057,1095),ns)
    section('national-2026-manuscripts','별첨 질의응답 (16)·(17) 원고료 지급',['manuscript'],nu(7,1239,1253),ns)
    section('national-2026-fee-faq','별첨 질의응답 (18)·(19) 강사료·원고료',['lecturer','manuscript'],nu(7,1254,1285),ns)
    section('national-2026-cards','Ⅰ 2-4·2-5. 지출내용 기록·정부구매카드 사용원칙',['card'],nu(3,358,366),ns)
    section('national-2026-assets','Ⅲ 17. 자산취득비(430-01목)',['assets'],nu(3,3957,3985),ns)
    def pu(page,start=None,end=None):
        original=pages[page-1];return dict(page=page,loc=f'PDF {page}쪽',text=clip(original['text'],start,end))
    section('local-446-supplies','별표 2의2 2-1. 사무관리비·일반수용비',['office_supplies'],[pu(66)],ls)
    section('local-446-overtime-meals','별표 2의2 2-1 마. 급식비',['overtime_meal'],[pu(68,'마. 급식비'),pu(69,end='바. 임차료')],ls)
    section('local-446-lecturers','별표 2의2 2-1 다 5) 공무원교육 외래강사료',['lecturer'],[pu(68,'5) 공무원교육 외래강사료','라. 피복비')],ls)
    section('local-446-meetings','별표 2의2 4. 업무추진비 공통사항',['meeting_meal'],[pu(76)],ls)
    section('local-446-cards','별표 4. 지방자치단체구매카드 발급 및 사용기준',['card'],[pu(i) for i in range(99,110)],ls)
    section('local-446-assets','별표 2의2 16-1. 자산 및 물품취득비',['assets'],[pu(94,end='16-2. 도서구입비')],ls)
    save(dest/'manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2).encode('utf-8'))
    return dict(sections=len(manifest),national_sections=8,local_sections=6,raw_documents=2,local_pdf_pages=len(pages),destination=str(dest))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--national',type=Path,required=True);parser.add_argument('--local',type=Path,required=True)
    parser.add_argument('--destination',type=Path,default=ROOT/'reference_data/finance-20261025')
    args=parser.parse_args();print(json.dumps(build(args.national,args.local,args.destination),ensure_ascii=False))
