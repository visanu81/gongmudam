"""Visitor material on the shared demo is removed once it is an hour old.

The demo was meant to reset when its container slept after 20 idle minutes,
but the container stayed up for hours (2026-11-03), so uploads and questions
stayed visible to every visitor until the next release. What a visitor adds
is removed after an hour; the demo material present at start stays.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import shutil

from . import folder_projects, folders

KEEP = timedelta(hours=1)
BUSY = {'queued', 'waiting', 'running'}


def _when(value):
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _old(value, cutoff):
    when = _when(value)
    return when is not None and when < cutoff


def snapshot(sandbox):
    """What the demo holds at start; none of it is removed."""
    with folder_projects.db() as c:
        projects = {r[0] for r in c.execute('SELECT id FROM folder_projects')}
        messages = {r[0] for r in c.execute('SELECT id FROM project_messages')}
    with folders.db() as c:
        libraries = {r[0] for r in c.execute('SELECT id FROM libraries')}
    incoming = sandbox / '추가회신'
    files = {p.name for p in incoming.iterdir()} if incoming.is_dir() else set()
    return dict(projects=projects, messages=messages, libraries=libraries, incoming=files)


def sweep(baseline, sandbox, now=None):
    """Remove visitor projects, questions, libraries and files older than an hour; return the counts."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - KEEP
    removed = dict(projects=0, messages=0, libraries=0, uploads=0, files=0)
    with folder_projects.db() as c:
        for (payload,) in c.execute('SELECT payload FROM folder_projects').fetchall():
            p = json.loads(payload)
            if p['id'] in baseline['projects'] or not _old(p.get('created_at'), cutoff):
                continue
            jobs = [json.loads(r[0]) for r in c.execute('SELECT payload FROM project_jobs WHERE project_id=?', (p['id'],))]
            if any(j.get('status') in BUSY for j in jobs):
                continue
            files = [r[0] for r in c.execute('SELECT id FROM project_files WHERE project_id=?', (p['id'],))]
            c.executemany('DELETE FROM project_units WHERE file_id=?', [(f,) for f in files])
            for table in ('project_sources', 'project_files', 'project_messages', 'project_jobs'):
                c.execute(f'DELETE FROM {table} WHERE project_id=?', (p['id'],))
            c.execute('DELETE FROM folder_projects WHERE id=?', (p['id'],))
            removed['projects'] += 1
        # Questions asked in the demo's own projects go too; their answers are separate messages.
        for (payload,) in c.execute('SELECT payload FROM project_messages').fetchall():
            m = json.loads(payload)
            if m['id'] in baseline['messages'] or m.get('status') in BUSY or not _old(m.get('created_at'), cutoff):
                continue
            c.execute('DELETE FROM project_messages WHERE id=?', (m['id'],))
            removed['messages'] += 1
    with folders.db() as c:
        for row in c.execute('SELECT id,payload FROM libraries').fetchall():
            if row[0] in baseline['libraries']:
                continue
            history = json.loads(row[1]).get('history') or [{}]
            if _old(history[0].get('at'), cutoff):
                c.execute('DELETE FROM libraries WHERE id=?', (row[0],))
                removed['libraries'] += 1
    stale = cutoff.timestamp()
    uploads = sandbox / 'uploads'
    for folder in uploads.iterdir() if uploads.is_dir() else ():
        if folder.is_dir() and not folder.is_symlink() and folder.stat().st_mtime < stale:
            shutil.rmtree(folder)
            removed['uploads'] += 1
    incoming = sandbox / '추가회신'
    for path in incoming.iterdir() if incoming.is_dir() else ():
        if path.name not in baseline['incoming'] and path.is_file() and path.stat().st_mtime < stale:
            path.unlink()
            removed['files'] += 1
    return removed
