"""Container entry: a fresh public demo runtime on every start.

Visitor edits live only for the container's lifetime. The image carries the
hash-checked public runtime template; the Upstage key arrives as a secret
environment variable and is never written into the image.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

TEMPLATE = Path('/app/service-template')
SERVICE = Path(os.environ.get('GONGMUDAM_SERVICE_ROOT', '/data/service'))


def prepare():
    if SERVICE.exists():
        shutil.rmtree(SERVICE)
    shutil.copytree(TEMPLATE, SERVICE)
    subprocess.run([sys.executable, '-X', 'utf8', 'tools/restore_submission.py'], cwd=SERVICE, check=True)
    config = json.loads((SERVICE / 'config.example.json').read_text(encoding='utf-8'))
    config['server'] = {'host': '0.0.0.0', 'port': 8080, 'open_browser': False}
    config['llm'] = json.loads((TEMPLATE / 'public-llm.json').read_text(encoding='utf-8'))
    (SERVICE / 'config.json').write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    incoming = SERVICE / 'synthetic-folders/추가회신'
    incoming.mkdir(parents=True, exist_ok=True)
    (incoming / '교육_참석_안내.txt').write_text(
        '합성 시연자료\n공공 AI 실무교육 참석 희망자를 취합합니다. 대상 부서는 총무과와 회계과입니다. 실제 개인정보를 입력하지 마세요.\n',
        encoding='utf-8')


if __name__ == '__main__':
    prepare()
    os.environ.update(GONGMUDAM_SERVICE_ROOT=str(SERVICE), GONGMUDAM_PUBLIC='1')
    # Upstage is remote, so the shared demo serves several judges at once (PC default: 30/h, 1 at a time).
    os.environ.setdefault('GONGMUDAM_PUBLIC_HOURLY', '300')
    os.environ.setdefault('GONGMUDAM_PUBLIC_CONCURRENCY', '8')
    os.execvp(sys.executable, [sys.executable, '-X', 'utf8', '-m', 'uvicorn', 'integration.application:create_app',
                               '--factory', '--host', '0.0.0.0', '--port', '8080'])
