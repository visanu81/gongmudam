"""Start the private B desktop using bundled sources, without a tunnel or Node."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import webbrowser

ROOT = Path(__file__).resolve().parents[1]


def free_port(port):
    with socket.socket() as probe:
        try:
            probe.bind(('127.0.0.1', port))
        except OSError as error:
            raise RuntimeError(f'Port {port} is in use. Close that server or run: run.bat --port 8787') from error


def ready(value, version):
    return (isinstance(value, dict) and value.get('status') == 'ok' and
            value.get('service_version') == version and value.get('desktop_connected') is True and
            value.get('public_demo') is False)


def open_when_ready(base, version):
    import httpx
    for _ in range(60):
        try:
            response = httpx.get(base + '/api/gongmudam/status', timeout=1)
            if response.status_code == 200 and ready(response.json(), version):
                webbrowser.open(base + '/desktop/?variant=B')
                return
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(.5)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8781)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error('port must be 1..65535')
    service = ROOT / 'service'
    version = json.loads((service / 'submission-manifest.json').read_text(encoding='utf-8'))['release_version']
    free_port(args.port)
    # Restore is idempotent and only rebases package-owned paths after relocation.
    subprocess.run([sys.executable, '-X', 'utf8', str(service / 'tools/restore_submission.py')], cwd=service, check=True)
    os.environ.update(GONGMUDAM_SERVICE_ROOT=str(service.resolve()), GONGMUDAM_PUBLIC='0')
    sys.path.insert(0, str(ROOT))
    url = f'http://127.0.0.1:{args.port}'
    print(f'Gongmudam {version}: {url}/desktop/?variant=B', flush=True)
    print('Keep this window open. Press Ctrl+C to stop. Local AI is optional.', flush=True)
    if not args.no_browser:
        threading.Thread(target=open_when_ready, args=(url, version), daemon=True).start()
    import uvicorn
    uvicorn.run('integration.application:create_app', factory=True, host='127.0.0.1', port=args.port)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
