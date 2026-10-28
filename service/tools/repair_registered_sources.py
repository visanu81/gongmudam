"""Add only the five previously reviewed national-service registrations.

Dry-run by default. Never restores or replaces a business database or enables a
source that the user disabled. Existing registrations and business rows survive.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid

from tools.restore_submission import safe_path

ROOT = Path(__file__).resolve().parents[1]
REVIEWED = {
    '156f83e9646084245c69e35ee1186cdbe52101ebe6489c0f7d134e90acca7f62': 20,
    '66d99077842d39bb41c3c36211f1977f55ed2e31c2ffdbf18e6185a21c777230': 26,
    'a454f317a1a87afbfb26d58cd040a6d3ac05aa4b1dbb75633deca3f37d02dc44': 25,
    'c4edc04864da363cc056b9ed5ccfd1086ac5364b3fcd356e9e8492a3c2489aae': 18,
    'f459b93473b181b1dc9333903d8ccc97f66930fc7954fabe074a2ff8628d3533': 19,
}


def selected_sources(root):
    bundle = json.loads((root / 'submission-data/knowledge.json').read_text(encoding='utf-8'))
    rows = [s for s in bundle['sources'] if s['id'].startswith('public-v70-')]
    if len(rows) != 5 or {s['sha256'] for s in rows} != set(REVIEWED):
        raise ValueError('Expected exactly the five reviewed source versions')
    for row in rows:
        official = row.get('official') or {}
        raw = safe_path(root, row['asset']).read_bytes()
        text = raw.decode('utf-8')
        number = REVIEWED[row['sha256']]
        if (hashlib.sha256(raw).hexdigest() != row['sha256'] or
                row['id'] != 'public-v70-' + row['sha256'][:24] or
                row['library_id'] != 'national-service-v70' or
                official.get('title') != '국가공무원 복무규정' or
                not official.get('article', '').startswith(f'제{number}조(') or
                official.get('sha256') != row['sha256'] or
                not row.get('units') or any(not u['text'] or u['text'] not in text for u in row['units'])):
            raise ValueError('Reviewed source validation failed: ' + row['id'])
    return rows


def protected_rows(c):
    """Digest all other tables; no user payload is returned or logged."""
    result = {}
    for (name,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
        if name in {'libraries', 'knowledge_sources'}:
            continue
        quoted = '"' + name.replace('"', '""') + '"'
        result[name] = c.execute('SELECT * FROM ' + quoted + ' ORDER BY rowid').fetchall()
    return result


def repair(root=ROOT, db_path=None, *, apply=False):
    root = Path(root).resolve()
    target = Path(db_path or root / 'data/folders.db').resolve()
    if not target.is_file():
        raise ValueError('Existing database is required; no database will be created')
    rows = selected_sources(root)
    c = sqlite3.connect(target, timeout=20)
    backup = None
    try:
        for table in ('knowledge_sources', 'libraries'):
            if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                raise ValueError('Existing registration schema is required')
        if apply:
            folder = target.parent / 'knowledge-repair-backups'
            folder.mkdir(exist_ok=True)
            backup = folder / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8] + '.db')
            with closing(sqlite3.connect(backup)) as saved:
                c.backup(saved)
        c.execute('BEGIN IMMEDIATE' if apply else 'BEGIN')
        original = c.execute('SELECT * FROM knowledge_sources ORDER BY rowid').fetchall()
        protected = protected_rows(c)
        missing, disabled = [], []
        for row in rows:
            existing = c.execute('SELECT payload,enabled FROM knowledge_sources WHERE id=?', (row['id'],)).fetchone()
            if existing:
                current = json.loads(existing[0])
                if any(current.get(k) != row[k] for k in ('sha256', 'library_id', 'file_id')):
                    raise ValueError('Existing registration differs; refusing to overwrite: ' + row['id'])
                if not existing[1]:
                    disabled.append(row['id'])
            else:
                if c.execute('SELECT 1 FROM knowledge_sources WHERE library_id=? AND file_id=?', (row['library_id'], row['file_id'])).fetchone():
                    raise ValueError('Another registration owns this file; review required')
                missing.append(row)
        result = dict(applied=apply, would_add=[s['id'] for s in missing], preserved_disabled=disabled)
        if not apply or not missing:
            c.rollback()
            return result | {'added': [], 'backup': str(backup) if backup else None}
        key = 'national-service-v70'
        existing = c.execute('SELECT version,payload FROM libraries WHERE id=?', (key,)).fetchone()
        if existing:
            version, raw = existing
            library = json.loads(raw)
        else:
            version = 0
            library = dict(id=key, name='국가공무원 복무규정 · 등록 보완', roots=[], files={}, projects={}, history=[], warnings=[])
        for source in missing:
            path = safe_path(root, source['asset'])
            fid = source['file_id']
            if fid in library['files'] and library['files'][fid].get('sha256') != source['sha256']:
                raise ValueError('Existing library file differs; refusing to overwrite')
            if fid not in library['files']:
                library['files'][fid] = dict(id=fid, name=source['official']['filename'], path=str(path), root=str(path.parent),
                    sha256=source['sha256'], units=source['units'], present=True, limited=False, status='본문 확인',
                    clues={}, suggestions=[], project_ids=[], bucket='common', manual=True, confirmed=True,
                    changed=False, review_reason='기존 제출본과 동일한 검증 원문 등록 보완')
            if str(path.parent) not in library['roots']:
                library['roots'].append(str(path.parent))
            payload = {k: v for k, v in source.items() if k not in {'asset', 'enabled'}}
            payload.update(path=str(path), library_name=library['name'])
            c.execute('INSERT INTO knowledge_sources VALUES(?,?,?,?,?)',
                (source['id'], key, fid, int(source['enabled']), json.dumps(payload, ensure_ascii=False)))
        library['version'] = version + 1
        library.setdefault('history', []).append(dict(at=datetime.now(timezone.utc).isoformat(), kind='누락된 법령 등록 보완', detail=result['would_add']))
        c.execute('INSERT INTO libraries VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET version=excluded.version,payload=excluded.payload',
                  (key, version + 1, json.dumps(library, ensure_ascii=False)))
        for row in original:
            if c.execute('SELECT * FROM knowledge_sources WHERE id=?', (row[0],)).fetchone() != row:
                raise ValueError('Existing registration was modified')
        if protected_rows(c) != protected:
            raise ValueError('Business rows were modified')
        c.commit()
        return result | {'added': result['would_add'], 'backup': str(backup), 'business_rows_preserved': True}
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(repair(db_path=args.db, apply=args.apply), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
