const STATIC_PREFIX = '/desktop/';
const STATIC_FILE = /\.(?:css|js|woff2?|ttf|png|jpe?g|svg|ico)$/;

export function offlineResponse(api = false) {
  const text = '공무담 공유 서버를 준비하는 중이거나 연결하지 못했어요. 잠시 후 다시 시도해 주세요.';
  return new Response(api ? JSON.stringify({detail: text, code: 'origin_unavailable'}) :
    `<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>공무담 연결 확인</title><body><main><h1>업무 서버 연결이 필요해요</h1><p>${text}</p><p><a href="/desktop/">공무담 바탕화면으로</a></p></main></body></html>`,
    {status: 503, headers: {'Content-Type': api ? 'application/json; charset=utf-8' : 'text/html; charset=utf-8', 'Cache-Control': 'no-store', 'Retry-After': '15'}});
}

export async function handle(request, env, backend = env.BACKEND) {
  const url = new URL(request.url);
  if (url.pathname === '/') return Response.redirect(url.origin + '/desktop/?variant=B', 307);
  if (url.pathname.startsWith(STATIC_PREFIX)) {
    if (!['GET', 'HEAD'].includes(request.method)) return new Response(null, {status: 405});
    if (url.pathname === STATIC_PREFIX) url.pathname += 'index.html';
    return env.ASSETS.fetch(new Request(url, request));
  }
  if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method)) {
    const origin = request.headers.get('Origin');
    if (origin && origin !== url.origin) return Response.json({detail: '다른 사이트의 요청은 허용하지 않습니다.'}, {status: 403});
    const length = Number(request.headers.get('Content-Length') || 0);
    if (length > 12 * 1024 * 1024) return Response.json({detail: '공개 시연 업로드 한도는 12MB입니다.'}, {status: 413});
  }
  const target = new URL(url.pathname + url.search, 'http://127.0.0.1:8892');
  const headers = new Headers(request.headers);
  // Origin was validated above; the private service sees its own loopback host.
  headers.delete('Origin');
  headers.delete('Host');
  headers.set('X-Forwarded-Host', url.host);
  headers.set('X-Forwarded-Proto', 'https');
  try {
    const response = await backend.fetch(new Request(target, {method: request.method,
      headers, body: ['GET', 'HEAD'].includes(request.method) ? undefined : request.body,
      duplex: 'half',
      redirect: 'manual'}));
    // A body nobody reads keeps the container's in-flight count up, so it never sleeps; close it.
    if (response.status >= 502) {
      await response.body?.cancel();
      return offlineResponse(url.pathname.startsWith('/api/'));
    }
    if (request.method === 'HEAD') await response.body?.cancel();
    const result = new Response(request.method === 'HEAD' ? null : response.body, response);
    const location = result.headers.get('Location');
    if (location) {
      const redirect = new URL(location, target);
      if (redirect.origin === target.origin) result.headers.set('Location', redirect.pathname + redirect.search + redirect.hash);
    }
    // Korean visitors are served from a European edge (colo CDG, 2026-11-04), about 1 s a
    // request, and a menu loads 50-90 scripts and styles. The browser may reuse those while
    // it revalidates them in the background (one stale load at most after a deploy); pages
    // and API answers are never reused.
    const reusable = request.method === 'GET' && response.status === 200 && !url.pathname.startsWith('/api/') &&
      STATIC_FILE.test(url.pathname);
    result.headers.set('Cache-Control', reusable ? 'public, max-age=0, stale-while-revalidate=600' : 'no-store');
    result.headers.set('X-Content-Type-Options', 'nosniff');
    return result;
  } catch {
    return offlineResponse(url.pathname.startsWith('/api/'));
  }
}

export default {fetch: handle};
