"""Requests to the personal app must come from its own screen on this PC.

A web page the user happens to open can otherwise send requests to the local
server: by naming another host that resolves to 127.0.0.1 (DNS rebinding) or
by posting from its own origin. The public demo has its own origin policy and
is not checked here. Ported from the teammate branch (r2/IR3 local boundary).
"""
import os
from urllib.parse import urlsplit
from fastapi.responses import JSONResponse

LOOPBACK = {'localhost', '127.0.0.1', '::1'}


def _allowed_hosts():
    extra = {h.strip().lower() for h in os.environ.get('GONGMUDAM_ALLOWED_HOSTS', '').split(',') if h.strip()}
    return LOOPBACK | extra


def check(request):
    """None when the request may proceed, otherwise the rejection response."""
    if getattr(request.app.state, 'public_demo', False):return None
    client = request.client.host if request.client else ''
    # Only browser traffic on this PC can be rebound; in-process test clients are not.
    if client not in LOOPBACK and os.environ.get('GONGMUDAM_HOST_CHECK') != '1':return None
    headers = request.headers
    hosts = headers.getlist('host')
    host = hosts[0] if len(hosts) == 1 else ''
    try:
        parsed = urlsplit('http://' + host)
        valid = (parsed.hostname in _allowed_hosts() and not parsed.username and not parsed.password
                 and not parsed.path and not parsed.query and not parsed.fragment)
        port = parsed.port or 80
    except ValueError:
        valid = False
    if not valid:return JSONResponse({'detail': '허용되지 않은 로컬 주소입니다. 이 PC의 공무담 화면에서 접속하세요.'}, status_code=400)
    if request.method in {'GET', 'HEAD', 'OPTIONS'}:return None
    if headers.get('sec-fetch-site') == 'cross-site':
        return JSONResponse({'detail': '다른 사이트에서 보낸 변경 요청은 허용하지 않습니다.'}, status_code=403)
    origins = headers.getlist('origin')
    if origins:
        try:
            origin = urlsplit(origins[0])
            same = (len(origins) == 1 and origin.scheme == request.url.scheme and origin.hostname == parsed.hostname
                    and (origin.port or (443 if origin.scheme == 'https' else 80)) == port
                    and not origin.path and not origin.query and not origin.fragment and not origin.username and not origin.password)
        except ValueError:
            same = False
        if not same:return JSONResponse({'detail': '이 PC의 공무담 화면에서 보낸 요청만 허용합니다.'}, status_code=403)
    return None
