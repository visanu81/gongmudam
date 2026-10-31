"""Compare the practice (실무 기준) block of the same questions on two installations."""
import argparse,json,sys
import httpx


def practice(client,url,question,today):
    response=client.post(url.rstrip('/')+'/api/ask',json={'query':question,'guidance':True,'use_ai':False,'today':today})
    response.raise_for_status()
    items=(response.json().get('guidance') or {}).get('practice') or []
    return [(i.get('sha256'),(i.get('official') or {}).get('publication'),i.get('loc')) for i in items]


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('--local','--public','--cases','--output'):parser.add_argument(name,required=True)
    parser.add_argument('--today',required=True)
    args=parser.parse_args(argv)
    cases=json.loads(open(args.cases,encoding='utf-8').read());rows=[]
    with httpx.Client(timeout=90.0) as client:
        for case in cases:
            local=practice(client,args.local,case['question'],args.today);public=practice(client,args.public,case['question'],args.today)
            rows.append(dict(id=case['id'],equal=local==public,local=local,public=public))
    summary=dict(total=len(rows),equal=sum(r['equal'] for r in rows),with_practice=sum(bool(r['local']) for r in rows))
    open(args.output,'w',encoding='utf-8').write(json.dumps(dict(summary=summary,cases=rows),ensure_ascii=False,indent=2))
    print(json.dumps(summary));return 0 if summary['equal']==summary['total'] else 1


if __name__=='__main__':sys.exit(main())
