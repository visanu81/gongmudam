"""Add reviewed finance sections without replacing existing libraries or work."""
import argparse
from contextlib import closing
from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3
import uuid

from app import finance_knowledge as finance
from tools.repair_registered_sources import protected_rows

ROOT=Path(__file__).resolve().parents[1]


def register(db_path=None,*,apply=False):
    target=Path(db_path or ROOT/'data/folders.db').resolve()
    if not target.is_file():raise ValueError('Existing database is required')
    rows=json.loads((finance.BASE/'manifest.json').read_text(encoding='utf-8'))
    if len(rows)!=14 or len({r['id'] for r in rows})!=14:raise ValueError('Unexpected finance pack')
    for row in rows:
        if finance.metadata(row['sha256'])!=row:raise ValueError('Finance source validation failed')
    with closing(sqlite3.connect(target,timeout=20)) as c:
        backup=None
        if apply:
            folder=target.parent/'finance-registration-backups';folder.mkdir(exist_ok=True)
            backup=folder/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8]+'.db')
            with closing(sqlite3.connect(backup)) as saved:c.backup(saved)
        try:
            c.execute('BEGIN IMMEDIATE' if apply else 'BEGIN')
            before=protected_rows(c)
            existing_sources=c.execute('SELECT * FROM knowledge_sources ORDER BY rowid').fetchall()
            existing_libraries=c.execute('SELECT * FROM libraries ORDER BY rowid').fetchall()
            additions=[]
            for row in rows:
                old=c.execute('SELECT payload FROM knowledge_sources WHERE id=?',(row['id'],)).fetchone()
                if old:
                    if json.loads(old[0])['sha256']!=row['sha256']:raise ValueError('Existing finance source differs; review required')
                    continue
                additions.append(row)
            result=dict(would_add=[r['id'] for r in additions],added=[],backup=str(backup) if backup else None)
            if not apply or not additions:c.rollback();return result
            # New immutable pack library: existing personal libraries never change.
            key='finance-20261025'
            if c.execute('SELECT 1 FROM libraries WHERE id=?',(key,)).fetchone():
                raise ValueError('Pack library already exists; refusing partial overwrite')
            lib=dict(id=key,version=1,name='예산·회계 공식 기준 · 2026',roots=[str(finance.BASE/'excerpts')],files={},projects={},warnings=[],history=[])
            for row in additions:
                fid=row['id'];path=finance.asset(finance.BASE/'excerpts',row['filename'])
                record=dict(id=fid,library_id=key,file_id=fid,library_name=lib['name'],title=row['title']+' '+row['article'],
                    path=str(path),sha256=row['sha256'],units=row['units'],limited=False,kind=row['kind'],institution=row['institution'],
                    effective_date=row['effective_date'],registered_at=datetime.now(timezone.utc).isoformat(),official=row)
                lib['files'][fid]=dict(id=fid,name=path.name,path=str(path),root=str(path.parent),sha256=row['sha256'],units=row['units'],
                    present=True,status='완전한 절·페이지 원문 등록',limited=False,clues={},suggestions=[],project_ids=[],bucket='common',
                    manual=True,confirmed=True,changed=False,review_reason='공식 예산·회계 원문의 검증된 절 사본')
                c.execute('INSERT INTO knowledge_sources VALUES(?,?,?,?,?)',(fid,key,fid,1,json.dumps(record,ensure_ascii=False)))
            lib['history'].append(dict(at=datetime.now(timezone.utc).isoformat(),kind='공식 예산·회계 자료 등록',detail={'sources':len(additions)}))
            c.execute('INSERT INTO libraries VALUES(?,?,?)',(key,1,json.dumps(lib,ensure_ascii=False)))
            if protected_rows(c)!=before:raise ValueError('Business rows changed')
            for row in existing_sources:
                if c.execute('SELECT * FROM knowledge_sources WHERE id=?',(row[0],)).fetchone()!=row:raise ValueError('Existing source changed')
            for row in existing_libraries:
                if c.execute('SELECT * FROM libraries WHERE id=?',(row[0],)).fetchone()!=row:raise ValueError('Existing library changed')
            c.commit();result.update(added=[r['id'] for r in additions],business_rows_preserved=True);return result
        except Exception:c.rollback();raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--db',type=Path);parser.add_argument('--apply',action='store_true')
    args=parser.parse_args();print(json.dumps(register(args.db,apply=args.apply),ensure_ascii=False,indent=2))
