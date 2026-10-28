"""Exercise project Q&A on an isolated local verification server (synthetic only)."""
from pathlib import Path
import argparse
import hashlib
import json
import time
import httpx
from openpyxl import Workbook
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject


def fixtures(root):
    root.mkdir(parents=True, exist_ok=True)
    (root/'교육 안내.txt').write_text('합성 검증자료\n교육 회신 마감은 2026-11-06입니다.\n참석 대상은 총무과와 회계과입니다.\n희망자 명단을 취합한 뒤 담당자가 최종 확인합니다.',encoding='utf-8')
    writer=PdfWriter()
    for n in range(1,26):
        page=writer.add_blank_page(width=500,height=700)
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
        stream=DecodedStreamObject()
        text='LATEDEADLINE 2026-11-06' if n==25 else f'ordinary page {n}'
        stream.set_data(f'BT /F1 12 Tf 50 650 Td ({text}) Tj ET'.encode('ascii'))
        page[NameObject('/Contents')]=writer._add_object(stream)
    with (root/'25쪽 교육자료.pdf').open('wb') as f:writer.write(f)
    book=Workbook()
    for n in range(2,7):book.create_sheet(f'시트{n}')
    book['시트6']['C501']='교육 회신 마감은 2026-11-06입니다.'
    book.save(root/'6개 시트 명단.xlsx')
    return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--base',default='http://127.0.0.1:8896')
    parser.add_argument('--fixtures',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--models',action='store_true')
    args=parser.parse_args()
    hashes=fixtures(args.fixtures)
    client=httpx.Client(base_url=args.base,headers={'Origin':args.base},timeout=15)
    def request(method,path,**kwargs):
        r=client.request(method,path,**kwargs);r.raise_for_status();return r.json()
    p=request('POST','/api/folder-projects',json={'name':'합성 교육 준비 · 실제 구동 검증'})
    pid=p['id'];prefix='/api/folder-projects/'+pid
    request('POST',prefix+'/sources',json={'kind':'folder','paths':[str(args.fixtures.resolve())]})
    def wait():
        end=time.monotonic()+200
        while time.monotonic()<end:
            value=request('GET',prefix)
            if value['messages'] and value['messages'][-1]['status'] in ('completed','failed'):
                return value['messages'][-1]
            time.sleep(.5)
        raise RuntimeError('답변 대기 시간 초과')
    def ask(q):
        request('POST',prefix+'/messages',json={'content':q})
        return wait()
    results=[]
    results.append({'scenario':'PDF 마지막 25쪽','answer':ask('LATEDEADLINE')})
    results.append({'scenario':'엑셀 여섯째 시트 501행','answer':ask('교육 회신 마감')})
    results.append({'scenario':'자료에 없는 질문','answer':ask('항공권 취소 수수료는 얼마인가요?')})
    results.append({'scenario':'보고서 초안','answer':ask('보고서 초안을 작성해줘')})
    draft=results[-1]['answer']
    request('PATCH',prefix+'/messages/'+draft['id'],json={'content':draft['content']+'\n담당자 검토 메모: 합성 검증 완료'})
    if args.models:
        original=request('GET','/api/settings')['llm']['active']
        try:
            for profile,model in [('local_gemma','gemma3:4b'),('local_llama','llama3.2:3b')]:
                request('PUT','/api/settings/llm',json={'profile':profile,'values':{'provider':'openai_compatible','base_url':'http://127.0.0.1:11434/v1','model':model,'timeout':120},'active':profile})
                started=time.monotonic();answer=ask('교육 회신 마감은 언제인가요?')
                results.append({'scenario':profile,'seconds':round(time.monotonic()-started,3),'answer':answer})
        finally:
            request('PUT','/api/settings/llm',json={'active':original})
    all_evidence=[e for r in results for e in r['answer'].get('evidence',[])]
    checks={'pdf_page25':any(e['loc']=='PDF 25쪽' and 'LATEDEADLINE' in e['text'] for e in results[0]['answer']['evidence']),
            'xlsx_sheet6_row501':any('시트6!C501' in e['loc'] for e in results[1]['answer']['evidence']),
            'no_unrelated_answer':not results[2]['answer']['evidence'],
            'draft_persisted':'담당자 검토 메모' in request('GET',prefix)['messages'][7]['content'],
            'originals_unchanged':hashes=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in args.fixtures.iterdir()},
            'citations_match':all(request('GET',prefix+f"/files/{e['file_id']}/units/{e['unit']}")['text']==e['text'] for e in all_evidence)}
    if args.models:
        checks['two_actual_models']=all(r['answer']['mode']=='local_ai' and r['answer']['model_metadata'].get('actual_response') and r['answer']['model']==r['answer']['model_metadata'].get('response_model') for r in results[-2:])
    evidence={'project_id':pid,'base':args.base,'checks':checks,'results':results,'passed':all(checks.values())}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'project_id':pid,'checks':checks,'passed':evidence['passed']},ensure_ascii=False))
    return int(not evidence['passed'])


if __name__=='__main__':raise SystemExit(main())
