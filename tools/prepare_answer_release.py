"""Stage code plus reviewed public sources; never read private application DBs.

The resulting candidate is consumed by upgrade_public_runtime.plan/upgrade.
Existing public sources and regulation certificates remain unchanged.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def wheel_key(name):return name.lower().replace('-','_').replace('.','_')


def copy_dependencies(source,dest):
    """Ship the current requirements and a wheel for every pinned package, so the offline install works.

    The managed list only knows the wheels of the first release; libraries added later
    (skdconv, pycryptodome, python-hwpx) were missing from the package.
    """
    for name in ('requirements.txt','requirements-travel.lock.txt'):shutil.copy2(source/name,dest/name)
    wheels={}
    for path in (source/'wheels').glob('*.whl'):
        package,version=path.name.split('-')[:2];wheels[(wheel_key(package),version)]=path
    for line in (source/'requirements-travel.lock.txt').read_text(encoding='utf-8').splitlines():
        line=line.split('#')[0].strip()
        if not line:continue
        package,version=line.split('==')
        wheel=wheels.get((wheel_key(package),version.strip()))
        if not wheel:raise ValueError('No bundled wheel for '+line)
        output=dest/'wheels'/wheel.name;output.parent.mkdir(exist_ok=True);shutil.copy2(wheel,output)


def prepare(dest, root=ROOT, version='v79-answer-first-20261026'):
    source=root/'service'; public=root/'.local-runtime/service';dest=Path(dest).resolve()
    if dest.exists():raise ValueError('Use a new candidate directory')
    old=read(public/'submission-manifest.json')
    if read(public/'gongmudam-runtime.json')['source_manifest_sha256']!=digest(public/'submission-manifest.json'):
        raise ValueError('Public runtime marker changed')
    dest.mkdir(parents=True)
    for name,expected in old['files'].items():
        relative=Path(name)
        if relative.is_absolute() or '..' in relative.parts:raise ValueError('Invalid managed path')
        origin=(source if name.startswith('wheels/') else public)/relative
        if digest(origin)!=expected:raise ValueError('Managed public file changed: '+name)
        output=dest/relative;output.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(origin,output)
    copy_dependencies(source,dest)
    # Immutable reviewed travel calculation packs must not change in a prose release.
    for previous in (public/'app/rulepacks').rglob('*'):
        if previous.is_file() and previous.suffix!='.pyc':
            current=source/previous.relative_to(public)
            if not current.is_file() or digest(previous)!=digest(current):raise ValueError('Travel rulepack requires separate review')
    for directory in ('app','static','reference_data','tests','tools'):
        shutil.copytree(source/directory,dest/directory,dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.pyo'))
    old_bundle=read(public/'submission-data/knowledge.json')
    reviewed=read(source/'submission-data/knowledge.json')
    existing={s['id']:s for s in old_bundle['sources']}
    following={s['id']:s for s in reviewed['sources']}
    pack=source/'reference_data/office-goods-20261026'
    goods_rows=read(pack/'manifest.json')
    goods_by_id={row['id']:row for row in goods_rows}
    for key,value in existing.items():
        if key in following:
            if following[key]!=value:raise ValueError('Existing reviewed source changed')
        elif key not in goods_by_id or value.get('official')!=goods_by_id[key] or value['sha256']!=goods_by_id[key]['sha256']:
            raise ValueError('Existing source is absent from the reviewed inputs')
    # Existing submission manifest fixes the selected public law/manual exports.
    verified=read(source/'submission-manifest.json')['files']
    for entry in reviewed['sources']:
        if entry['id'] in existing:continue
        host=urlsplit((entry.get('official') or {}).get('source_url','')).hostname or ''
        if entry['kind'] not in ('법령·규정','기관 지침') or not host.endswith('.go.kr'):
            raise ValueError('Only reviewed official public sources may be added')
        asset=Path(entry['asset'])
        if asset.is_absolute() or '..' in asset.parts or asset.parts[:2]!=('submission-data','sources'):
            raise ValueError('Invalid source asset')
        if verified.get(asset.as_posix())!=entry['sha256'] or digest(source/asset)!=entry['sha256']:
            raise ValueError('Source is not the reviewed submission asset')
        out=dest/asset;out.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source/asset,out)
        old_bundle['sources'].append(entry)
    # New goods pack consists exclusively of pinned official law articles.
    for row in goods_rows:
        if row['id'] in existing:continue
        if row['collection']!='office-goods-20261026' or not row['source_url'].startswith('https://www.law.go.kr/'):
            raise ValueError('Unexpected goods source')
        if digest(pack/'raw'/row['raw_file'])!=row['raw_sha256'] or digest(pack/'excerpts'/row['filename'])!=row['sha256']:
            raise ValueError('Pinned goods source changed')
        asset='submission-data/sources/office-goods-20261026/'+row['sha256']+'.txt'
        out=dest/asset;out.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(pack/'excerpts'/row['filename'],out)
        old_bundle['sources'].append(dict(id=row['id'],library_id=row['collection'],file_id=row['id'],
            title=row['title']+' '+row['article'],sha256=row['sha256'],units=row['units'],limited=False,
            kind=row['kind'],institution=row['institution'],effective_date=row['effective_date'],
            official=row,asset=asset,enabled=1,library_name='국가·지방 물품관리 공식 근거'))
    old_bundle['created_at']=datetime.now(timezone.utc).isoformat()
    save(dest/'submission-data/knowledge.json',old_bundle)
    manifest=dict(old, release_version=version,sources=len(old_bundle['sources']),
                  created_at=datetime.now(timezone.utc).isoformat())
    manifest.pop('hotfix',None)
    manifest['files']={p.relative_to(dest).as_posix():digest(p) for p in sorted(dest.rglob('*')) if p.is_file()}
    save(dest/'submission-manifest.json',manifest)
    return dict(candidate=str(dest),sources=manifest['sources'],files=len(manifest['files']),private_databases_read=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--dest',type=Path,required=True)
    parser.add_argument('--version',default='v79-answer-first-20261026',help='release_version shown by the runtime')
    args=parser.parse_args();print(json.dumps(prepare(args.dest,version=args.version),ensure_ascii=False,indent=2))
