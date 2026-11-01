"""Install kordoc for PDF reading in 업무자료 정리 (optional; needs Node.js 20+).

Without it the app keeps reading PDFs with its built-in reader. Only the PDF
part is installed: OCR and image add-ons are optional dependencies and are
left out. Versions are pinned; the cloud container installs the same pair.
"""
from pathlib import Path
import json
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / '.local-runtime' / 'kordoc'
PACKAGES = ('kordoc@4.24.33', 'pdfjs-dist@4.10.38')


def install():
    node, npm = shutil.which('node'), shutil.which('npm') or shutil.which('npm.cmd')
    if not node or not npm:
        raise SystemExit('Node.js 20 이상을 설치한 뒤 다시 실행하세요. 설치하지 않아도 PDF는 기본 해석기로 읽습니다.')
    version = subprocess.run([node, '--version'], capture_output=True, text=True, check=True).stdout.strip()
    if int(version.lstrip('v').split('.')[0]) < 20:
        raise SystemExit(f'Node.js {version}는 너무 오래됐습니다. 20 이상이 필요합니다.')
    TARGET.mkdir(parents=True, exist_ok=True)
    (TARGET / 'package.json').write_text(json.dumps({'name': 'gongmudam-kordoc', 'private': True}), encoding='utf-8')
    subprocess.run([npm, 'install', '--omit=optional', '--no-audit', '--no-fund', '--ignore-scripts', *PACKAGES],
                   cwd=TARGET, check=True)
    cli = TARGET / 'node_modules/kordoc/dist/cli.js'
    if not cli.is_file():
        raise SystemExit('kordoc 설치를 확인하지 못했습니다.')
    return {'node': version, 'cli': str(cli), 'packages': list(PACKAGES)}


if __name__ == '__main__':
    print(json.dumps(install(), ensure_ascii=False))
    sys.exit(0)
