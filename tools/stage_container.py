"""Stage the public demo container build context; never copies private data.

Only files listed in the public runtime's submission manifest are copied, each
checked against its SHA-256. Runtime DBs, config.json (which may hold an API
key), backups and visitor folders are excluded; the container rebuilds them.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / '.local-runtime/service'
CONTAINER = ROOT / 'cloudflare/container'
MARKER = '.gongmudam-container-stage'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stage(dest):
    dest = Path(dest).resolve()
    # Only a directory this tool staged before may be replaced.
    if dest.exists() and (dest / MARKER).is_file():
        shutil.rmtree(dest)
    if dest.exists():
        raise ValueError('Use a new staging directory')
    manifest = json.loads((RUNTIME / 'submission-manifest.json').read_text(encoding='utf-8'))
    template = dest / 'service-template'
    for name, expected in manifest['files'].items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Invalid managed path: ' + name)
        if name.startswith('wheels/'):
            continue
        source = RUNTIME / relative
        if digest(source) != expected:
            raise ValueError('Managed public file changed: ' + name)
        target = template / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    shutil.copy2(RUNTIME / 'submission-manifest.json', template / 'submission-manifest.json')
    definition = json.loads((RUNTIME / 'public-demo.json').read_text(encoding='utf-8'))
    if definition.get('mode') != 'public-synthetic-demo' or definition.get('private_data_isolated') is not True:
        raise ValueError('Runtime is not an isolated public demo')
    # The container creates its own demo library on start.
    definition['folder_library_id'] = 'gongmudam-demo'
    (template / 'public-demo.json').write_text(json.dumps(definition, ensure_ascii=False, indent=2), encoding='utf-8')
    llm = json.loads((RUNTIME / 'config.json').read_text(encoding='utf-8'))['llm']
    for profile in llm['profiles'].values():
        profile['api_key'] = ''
    (template / 'public-llm.json').write_text(json.dumps(llm, ensure_ascii=False, indent=2), encoding='utf-8')
    shutil.copytree(ROOT / 'integration', dest / 'integration', ignore=shutil.ignore_patterns('__pycache__'))
    # Only the public agency directory is taken from desktop/data (see .gitignore).
    shutil.copytree(ROOT / 'desktop', dest / 'desktop',
                    ignore=shutil.ignore_patterns('__pycache__', 'tests', 'tools', 'evidence', 'runtime-logs', 'data'))
    (dest / 'desktop/data').mkdir()
    for name in ('agencies-v1.sqlite', 'agencies-v1.json'):
        shutil.copy2(ROOT / 'desktop/data' / name, dest / 'desktop/data' / name)
    for name in ('Dockerfile', 'start.py', 'requirements.txt'):
        shutil.copy2(CONTAINER / name, dest / name)
    leaked = [p for p in dest.rglob('*') if p.name in {'config.json', 'folders.db', 'seomu.db', 'travel.db'}]
    if leaked:
        raise ValueError('Private runtime file staged: ' + ', '.join(map(str, leaked)))
    (dest / MARKER).write_text(manifest['release_version'] + '\n', encoding='utf-8')
    # The Worker names the container instance after this release, so a deploy starts a fresh one.
    (dest / 'release.json').write_text(json.dumps({'version': manifest['release_version']}), encoding='utf-8')
    return dict(staged=str(dest), files=sum(1 for p in dest.rglob('*') if p.is_file()),
                version=manifest['release_version'], private_data_copied=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dest', type=Path, required=True)
    print(json.dumps(stage(parser.parse_args().dest), ensure_ascii=False, indent=2))
