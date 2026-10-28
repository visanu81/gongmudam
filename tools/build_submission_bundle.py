"""Build an explicit local-only submission from the verified service and B UI."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ('index.html', 'desktop.css', 'desktop.js', 'home-agenda.js', 'home-agenda.css', 'quote-strip.js', 'quote-strip.css', 'service-bridge.css', 'service-bridge.js',
           'embedded.css', 'embedded.js', 'window-resize.css', 'window-resize.js',
           'agency-picker.js', 'calculator.js', 'notepad.js', 'agency_directory.py', 'deployment-context.js', 'service-entry.js')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(root, name):
    value = PurePosixPath(name)
    if value.is_absolute() or '..' in value.parts or ':' in name or '\\' in name:
        raise ValueError('Unsafe manifest path')
    result = (root / name).resolve()
    if not result.is_relative_to(root.resolve()) or result == root.resolve():
        raise ValueError('Path outside package')
    return result


def build(destination, archive=None, service_root=None):
    destination = destination.resolve()
    if destination.exists():
        raise ValueError('Use a new destination; existing files are preserved')
    service_root = Path(service_root).resolve() if service_root is not None else ROOT / 'service'
    service_manifest_path = service_root / 'submission-manifest.json'
    service_manifest = json.loads(service_manifest_path.read_text(encoding='utf-8'))
    version = service_manifest['release_version']
    if not isinstance(version, str) or not re.fullmatch(r'v\d+', version):
        raise ValueError('Unsupported release version')
    wanted = {}
    for name, expected in service_manifest['files'].items():
        if (PurePosixPath(name).parts[0] in {'data', 'output', '.venv', '.git', 'node_modules'} or
                PurePosixPath(name).name in {'config.json', '.env'}):
            raise ValueError('Private runtime file is not submission content: ' + name)
        path = relative(service_root, name)
        if sha(path) != expected:
            raise ValueError('Service hash mismatch: ' + name)
        wanted['service/' + name] = path
    wanted['service/submission-manifest.json'] = service_manifest_path
    for name in DESKTOP:
        wanted['desktop/' + name] = ROOT / 'desktop' / name
    wanted['desktop/tests/test_agency_directory.py'] = ROOT / 'desktop/tests/test_agency_directory.py'
    for path in (ROOT / 'desktop/assets').iterdir():
        if path.is_file() and path.suffix in {'.svg', '.png', '.woff2', '.txt'}:
            wanted[path.relative_to(ROOT).as_posix()] = path
    wanted['desktop/data/agencies-v1.sqlite'] = ROOT / 'desktop/data/agencies-v1.sqlite'
    for name in ('__init__.py', 'application.py'):
        wanted['integration/' + name] = ROOT / 'integration' / name
    for name in ('run_local_app.py', 'build_submission_bundle.py'):
        wanted['tools/' + name] = ROOT / 'tools' / name
    for name in ('test_integration.py', 'test_local_run.py', 'test_submission_bundle.py', 'service-bridge.test.mjs', 'window-resize.test.mjs', 'deployment-context.test.mjs', 'home-agenda.test.mjs', 'quote-strip.test.mjs', 'service-entry.test.mjs', 'service-navigation.test.mjs', 'embedded-affiliation.test.mjs'):
        wanted['tests/' + name] = ROOT / 'tests' / name
    # Test fixture imports use these developer helpers; none starts a server on import.
    for name in ('prepare_public_runtime.py', 'upgrade_public_runtime.py'):
        wanted['tools/' + name] = ROOT / 'tools' / name
    for name in ('LOCAL-AI-v71-20261025.txt', f'SUBMISSION-{version}-START.txt', f'SUBMISSION-{version}-VALIDATION.txt'):
        wanted['docs/' + name] = ROOT / 'docs' / name
    for name in ('HOME-AGENDA-20261025.txt', 'SUBMISSION-v72-VALIDATION.txt'):
        if (ROOT / 'docs' / name).is_file():
            wanted['docs/' + name] = ROOT / 'docs' / name
    for name in ('SUBMISSION-v74-VALIDATION.txt', 'evidence/v74/fresh-projects.json', 'evidence/v74/fresh-validation-summary.json'):
        path = ROOT / 'docs' / name
        if path.is_file():
            wanted['docs/' + name] = path
    for group in dict.fromkeys(('v71', 'v72', version)):
        folder = ROOT / 'docs/evidence' / group
        if folder.exists():
            for path in folder.iterdir():
                # Keep development reproductions locally; publish final evidence.
                if path.is_file() and path.suffix in {'.json', '.png', '.jpg', '.jpeg', '.txt'} and not path.stem.endswith('-initial'):
                    wanted[path.relative_to(ROOT).as_posix()] = path
    for name, path in wanted.items():
        if not path.is_file():
            raise ValueError('Required submission file is missing: ' + name)
    destination.mkdir(parents=True)
    for name, path in wanted.items():
        target = relative(destination, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    install = ('@echo off\r\nsetlocal\r\ncd /d "%~dp0"\r\n'
               'if not exist "service\\.venv\\Scripts\\python.exe" (\r\n'
               '  py -3.12 -c "import struct; raise SystemExit(0 if struct.calcsize(\'P\') == 8 else 1)" >nul 2>&1\r\n'
               '  if errorlevel 1 (\r\n    echo Install Python 3.12 x64 first. Read the getting-started text file.\r\n    exit /b 1\r\n  )\r\n)\r\n'
               'cd /d "%~dp0service"\r\n'
               'if errorlevel 1 exit /b 1\r\ncall install-submission.bat %*\r\n'
               'set "result=%errorlevel%"\r\nendlocal & exit /b %result%\r\n')
    run = ('@echo off\r\nsetlocal\r\ncd /d "%~dp0"\r\n'
           'if not exist "service\\.venv\\Scripts\\python.exe" (\r\n'
           '  echo Run install.bat first. Python 3.12 x64 is required.\r\n  exit /b 1\r\n)\r\n'
           '"service\\.venv\\Scripts\\python.exe" -X utf8 tools\\run_local_app.py %*\r\n'
           'set "result=%errorlevel%"\r\nendlocal & exit /b %result%\r\n')
    for name, body in [('install.bat', install), ('run.bat', run)]:
        (destination / name).write_bytes(body.encode('ascii'))
    for name, command in [('1_설치.bat', 'install.bat'), ('2_공무담_실행.bat', 'run.bat')]:
        tail = 'pause\r\n' if command == 'install.bat' else 'if errorlevel 1 pause\r\n'
        (destination / name).write_bytes(('@echo off\r\ncd /d "%~dp0"\r\ncall ' + command + ' %*\r\n' + tail).encode('ascii'))
    shutil.copyfile(ROOT / f'docs/SUBMISSION-{version}-START.txt', destination / '처음읽기.txt')
    files = {p.relative_to(destination).as_posix(): sha(p) for p in sorted(destination.rglob('*')) if p.is_file()}
    manifest = {'format': 1, 'product': '공무담', 'release_version': service_manifest['release_version'],
                'created_at': datetime.now(timezone.utc).isoformat(),
                'target': 'Windows x64 Python 3.12; local private B desktop; AI optional',
                'registered_sources': service_manifest['sources'], 'files': files}
    (destination / 'gongmudam-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    result = {'version': manifest['release_version'], 'files': len(files), 'destination': str(destination)}
    if archive:
        archive = archive.resolve()
        if archive.exists():
            raise ValueError('Archive already exists; preserve older releases')
        archive.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
            for path in sorted(destination.rglob('*')):
                if path.is_file():
                    output.write(path, '공무담/' + path.relative_to(destination).as_posix())
        result.update(archive=str(archive), sha256=sha(archive), bytes=archive.stat().st_size)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--service-root', type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.destination, args.archive, args.service_root), ensure_ascii=False))


if __name__ == '__main__':
    main()
