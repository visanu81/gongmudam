import test from 'node:test';
import assert from 'node:assert/strict';
import {handle} from '../cloudflare/worker.js';

test('root opens the B desktop at the fixed origin', async () => {
  const result = await handle(new Request('https://gongmudam.visanu81.workers.dev/'), {});
  assert.equal(result.status, 307);
  assert.equal(result.headers.get('Location'), 'https://gongmudam.visanu81.workers.dev/desktop/?variant=B');
});
test('desktop assets work independently of the PC', async () => {
  const result = await handle(new Request('https://g.test/desktop/index.html'), {ASSETS: {fetch: () => new Response('desktop')}});
  assert.equal(await result.text(), 'desktop');
});
test('API preserves query, method, body and download headers', async () => {
  let seen;
  const backend = {async fetch(request) {seen = request; assert.equal(await request.text(), 'file'); return new Response('saved', {headers: {'Content-Disposition': 'attachment; filename=test.pdf'}});}};
  const result = await handle(new Request('https://g.test/api/toolbox?a=1', {method: 'POST', headers: {Origin: 'https://g.test'}, body: 'file'}), {BACKEND: backend});
  assert.equal(seen.url, 'http://127.0.0.1:8892/api/toolbox?a=1');
  assert.equal(seen.method, 'POST');
  assert.equal(seen.headers.get('Origin'), null);
  assert.match(result.headers.get('Content-Disposition'), /test.pdf/);
});
test('cross origin writes and large uploads never reach PC', async () => {
  const backend = {fetch() {throw Error('must not fetch');}};
  assert.equal((await handle(new Request('https://g.test/api/ask', {method: 'POST', headers: {Origin: 'https://other.test'}, body: '{}'}), {BACKEND: backend})).status, 403);
  assert.equal((await handle(new Request('https://g.test/api/upload', {method: 'POST', headers: {'Content-Length': String(13 * 1024 * 1024)}}), {BACKEND: backend})).status, 413);
});
test('offline backend gives an honest retryable error', async () => {
  const result = await handle(new Request('https://g.test/api/ask'), {BACKEND: {fetch() {throw Error('offline');}}});
  assert.equal(result.status, 503);
  assert.equal((await result.json()).code, 'origin_unavailable');
});
test('backend redirects keep users on the public origin', async () => {
  const result = await handle(new Request('https://g.test/api/result'), {BACKEND: {fetch() {return new Response(null, {status: 307, headers: {Location: 'http://127.0.0.1:8892/travel.html?case=abc#settle'}});}}});
  assert.equal(result.headers.get('Location'), '/travel.html?case=abc#settle');
});
test('bodies the worker does not pass on are closed so the container can sleep', async () => {
  for (const [method, status] of [['GET', 503], ['HEAD', 200]]) {
    let cancelled = false;
    const body = new ReadableStream({cancel() {cancelled = true;}});
    const result = await handle(new Request('https://g.test/api/status', {method}), {BACKEND: {fetch() {return new Response(body, {status});}}});
    assert.equal(cancelled, true, method);
    assert.equal(method === 'HEAD' ? result.body : result.status, method === 'HEAD' ? null : 503);
  }
});
test('scripts and styles may be reused while pages and answers never are', async () => {
  const backend = {fetch() {return new Response('x', {headers: {'Cache-Control': 'no-cache'}});}};
  const header = async (path, init) => (await handle(new Request('https://g.test' + path, init), {BACKEND: backend})).headers.get('Cache-Control');
  for (const path of ['/app.js', '/style.css', '/fonts/a.woff2', '/travel-demo-hotel.png'])
    assert.equal(await header(path), 'public, max-age=300, stale-while-revalidate=600', path);
  for (const path of ['/index.html', '/calendar.html', '/api/knowledge/sources', '/api/x.js'])
    assert.equal(await header(path), 'no-store', path);
  assert.equal(await header('/app.js', {method: 'HEAD'}), 'no-store');
  const confirmed = {fetch() {return new Response(null, {status: 304});}};
  assert.match((await handle(new Request('https://g.test/app.js'), {BACKEND: confirmed})).headers.get('Cache-Control'), /max-age=300/);
  const assets = {fetch() {return new Response('file', {headers: {'Cache-Control': 'public, max-age=0, must-revalidate'}});}};
  assert.match((await handle(new Request('https://g.test/desktop/desktop.js'), {ASSETS: assets})).headers.get('Cache-Control'), /max-age=300/);
  assert.match((await handle(new Request('https://g.test/desktop/'), {ASSETS: assets})).headers.get('Cache-Control'), /max-age=0/);
  const missing = {fetch() {return new Response('no', {status: 404});}};
  assert.equal((await handle(new Request('https://g.test/gone.js'), {BACKEND: missing})).headers.get('Cache-Control'), 'no-store');
});
