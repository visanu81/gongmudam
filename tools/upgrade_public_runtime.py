"""Explicit, backed-up additive upgrade of an existing public demo.

The app must be stopped. User DB rows, settings, attachments and regulation
certificates are preserved. A changed registered source needs separate review.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import socket
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def database(path):
    connection = sqlite3.connect(path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def owned(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or path == root.resolve():
        raise ValueError('Path escapes the runtime: ' + name)
    return path


def plan(source, target):
    source, target = source.resolve(), target.resolve()
    new, old = read(source / 'submission-manifest.json'), read(target / 'submission-manifest.json')
    if read(target / 'gongmudam-runtime.json')['source_manifest_sha256'] != digest(target / 'submission-manifest.json'):
        raise ValueError('Runtime marker differs; inspect the existing runtime first')
    for root, manifest in ((source, new), (target, old)):
        for name, expected in manifest['files'].items():
            if root == target and name.startswith('wheels/'):
                continue
            path = owned(root, name)
            if not path.is_file() or digest(path) != expected:
                raise ValueError('Managed file was changed: ' + str(path))
    # Wheels are not installed in the runtime, so a wheel replaced by a newer pin may leave the list.
    if any(not name.startswith('wheels/') for name in old['files'].keys() - new['files'].keys()):
        raise ValueError('This upgrade cannot remove managed files')
    before, after = read(target / 'submission-data/knowledge.json'), read(source / 'submission-data/knowledge.json')
    if before.get('regulation_snapshot') != after.get('regulation_snapshot') or before.get('regulation_objects') != after.get('regulation_objects'):
        raise ValueError('Regulation evidence changes require a separate review')
    previous = {item['id']: item for item in before['sources']}
    following = {item['id']: item for item in after['sources']}
    if len(previous) != len(before['sources']) or len(following) != len(after['sources']):
        raise ValueError('Duplicate source IDs')
    for key, value in previous.items():
        if following.get(key) != value:
            raise ValueError('Existing registered source changes require review: ' + key)
    additions = [item for key, item in following.items() if key not in previous]
    marker = read(target / 'data/submission-installation.json')
    if marker['root'] != str(target) or marker['bundle_sha256'] != digest(target / 'submission-data/knowledge.json'):
        raise ValueError('Installation paths or bundle marker differ')
    with database(target / 'data/folders.db') as connection:
        for key, value in previous.items():
            row = connection.execute('SELECT library_id,file_id,payload FROM knowledge_sources WHERE id=?', (key,)).fetchone()
            if not row or row[:2] != (value['library_id'], value['file_id']) or json.loads(row[2])['sha256'] != value['sha256']:
                raise ValueError('Installed source changed or was removed: ' + key)
        for item in additions:
            if connection.execute('SELECT 1 FROM knowledge_sources WHERE id=? OR (library_id=? AND file_id=?)',
                                  (item['id'], item['library_id'], item['file_id'])).fetchone():
                raise ValueError('New source conflicts with an existing registration')
            if connection.execute('SELECT 1 FROM libraries WHERE id=?', (item['library_id'],)).fetchone():
                raise ValueError('Adding to an existing library requires a separate review')
    changed = [name for name, value in new['files'].items()
               if old['files'].get(name) != value and not name.startswith('wheels/')]
    return {'from': old['release_version'], 'to': new['release_version'], 'changed': changed,
            'additions': additions, 'sources': len(following)}


def addition_rows(source, target, additions, stage):
    """Use the shipped restore serializer; only append genuinely new records."""
    if not additions:
        return [], []
    stage.mkdir()
    (stage / 'data').mkdir()
    for item in additions:
        destination = owned(stage, item['asset'])
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(owned(source, item['asset']), destination)
    sys.path.insert(0, str(source))
    spec = importlib.util.spec_from_file_location('gongmudam_restore_upgrade', source / 'tools/restore_submission.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.install_knowledge(stage, {'sources': additions})

    def rebase(value):
        if isinstance(value, str) and value.startswith(str(stage) + str(Path('/'))):
            return str(target / Path(value).relative_to(stage))
        if isinstance(value, list):
            return [rebase(item) for item in value]
        if isinstance(value, dict):
            return {key: rebase(item) for key, item in value.items()}
        return value

    with database(stage / 'data/folders.db') as connection:
        sources = [tuple(row[:4]) + (json.dumps(rebase(json.loads(row[4])), ensure_ascii=False),)
                   for row in connection.execute('SELECT id,library_id,file_id,enabled,payload FROM knowledge_sources')]
        libraries = [(row[0], row[1], json.dumps(rebase(json.loads(row[2])), ensure_ascii=False))
                     for row in connection.execute('SELECT id,version,payload FROM libraries')]
    return sources, libraries


def upgrade(source, target, backup_root):
    source, target = source.resolve(), target.resolve()
    change = plan(source, target)
    if (not change['changed'] and not change['additions']
            and digest(source / 'submission-manifest.json') == digest(target / 'submission-manifest.json')):
        return {'status': 'already_current', 'version': change['to']}
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = backup_root.resolve() / stamp
    backup.mkdir(parents=True)
    lock = target / 'data/gongmudam-upgrade.lock'
    with lock.open('x'):
        pass
    written = []
    db_replaced = False
    files = change['changed'] + ['submission-manifest.json', 'gongmudam-runtime.json', 'data/submission-installation.json']
    try:
        # Back up mutable data before touching it; sqlite.backup includes WAL pages.
        for folder in ('data', 'output', 'synthetic-folders'):
            if (target / folder).exists():
                shutil.copytree(target / folder, backup / folder)
        for path in (target / 'data').glob('*.db'):
            with database(path) as current, database(backup / 'data' / path.name) as saved:
                current.backup(saved)
        if (target / 'config.json').exists():
            shutil.copy2(target / 'config.json', backup / 'config.json')
        for name in files:
            path = owned(target, name)
            if path.exists():
                saved = owned(backup / 'managed', name)
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, saved)
        with tempfile.TemporaryDirectory(prefix='gongmudam-upgrade-', dir=backup) as tmp:
            stage = Path(tmp)
            rows, libraries = addition_rows(source, target, change['additions'], stage / 'new-sources')
            staged_db = stage / 'folders.db'
            with database(target / 'data/folders.db') as current, database(staged_db) as updated:
                current.backup(updated)
                with updated:
                    updated.executemany('INSERT INTO libraries(id,version,payload) VALUES(?,?,?)', libraries)
                    updated.executemany('INSERT INTO knowledge_sources(id,library_id,file_id,enabled,payload) VALUES(?,?,?,?,?)', rows)
                if updated.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('Updated source database is invalid')
            for name in change['changed'] + ['submission-manifest.json']:
                path = owned(target, name)
                path.parent.mkdir(parents=True, exist_ok=True)
                written.append(name)
                shutil.copy2(owned(source, name), path)
            # Use SQLite backup instead of replacing a DB next to old WAL files.
            with database(staged_db) as updated, database(target / 'data/folders.db') as current:
                db_replaced = True
                updated.backup(current)
            installation = read(target / 'data/submission-installation.json')
            installation.update(bundle_sha256=digest(source / 'submission-data/knowledge.json'), sources=change['sources'])
            for name, payload in [('data/submission-installation.json', installation),
                                  ('gongmudam-runtime.json', {'source_manifest_sha256': digest(source / 'submission-manifest.json')})]:
                written.append(name)
                owned(target, name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        result = {'status': 'upgraded', 'from': change['from'], 'to': change['to'],
                  'files_updated': len(change['changed']), 'sources_added': len(change['additions']), 'backup': str(backup)}
        (backup / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        return result
    except Exception:
        if db_replaced:
            with database(backup / 'data/folders.db') as saved, database(target / 'data/folders.db') as current:
                saved.backup(current)
        for name in reversed(written):
            path, saved = owned(target, name), owned(backup / 'managed', name)
            if saved.exists():
                shutil.copy2(saved, path)
            elif path.exists():
                path.unlink()
        raise
    finally:
        lock.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--source', type=Path, default=ROOT / 'service',
                        help='prepared public runtime candidate (default: service)')
    args = parser.parse_args()
    source, target = args.source.resolve(), (ROOT / '.local-runtime/service').resolve()
    if not args.apply:
        result = plan(source, target)
        print(json.dumps({key: value if key != 'additions' else [s['title'] for s in value]
                          for key, value in result.items()}, ensure_ascii=False, indent=2))
        return
    with socket.socket() as connection:
        if connection.connect_ex(('127.0.0.1', 8892)) == 0:
            raise RuntimeError('Stop the Gongmudam server on port 8892 before upgrading')
    print(json.dumps(upgrade(source, target, ROOT / '.local-runtime/upgrades'), ensure_ascii=False))


if __name__ == '__main__':
    main()
