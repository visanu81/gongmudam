import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../desktop/deployment-context.js', import.meta.url), 'utf8');

function setup(fetchImpl) {
  const listeners = new Map();
  const title = { textContent: '' };
  const description = { textContent: '' };
  const mode = { textContent: '' };
  const notice = { children: [title, description] };
  const document = {
    readyState: 'loading',
    querySelector: (selector) => selector === '.prototype-notice' ? notice : selector === '.mode-label' ? mode : null,
    addEventListener: (type, handler) => listeners.set(type, handler),
  };
  const window = { fetch: fetchImpl };
  vm.runInNewContext(source, { window, document });
  return { api: window.GongmudamEnvironment, listeners, title, description, mode };
}

test('public status retains the public notice and badge; status fetch is cached', async () => {
  let calls = 0;
  const ui = setup(async () => { calls++; return { ok: true, json: async () => ({ status: 'ok', desktop_connected: true, public_demo: true }) }; });
  const first = await ui.api.get();
  const second = await ui.api.get();
  assert.equal(calls, 1);
  assert.equal(first.known, true);
  assert.equal(first.publicDemo, true);
  assert.equal(second, first);
  ui.listeners.get('DOMContentLoaded')();
  await Promise.resolve(); await Promise.resolve();
  assert.equal(ui.title.textContent, '공무담 공개 시연');
  assert.equal(ui.description.textContent, '모든 방문자가 같은 공개 시연을 봅니다. 실제 개인정보나 업무 자료를 입력하지 마세요.');
  assert.equal(ui.mode.textContent, '공개 시연');
});

test('private status labels the local workspace', async () => {
  const ui = setup(async () => ({ ok: true, json: async () => ({ status: 'ok', desktop_connected: true, public_demo: false }) }));
  assert.deepEqual({ ...(await ui.api.get()) }, { known: true, publicDemo: false });
  ui.listeners.get('DOMContentLoaded')();
  await Promise.resolve(); await Promise.resolve();
  assert.equal(ui.title.textContent, '내 PC 업무 공간');
  assert.equal(ui.description.textContent, '업무와 등록 자료는 이 PC에 저장됩니다.');
  assert.equal(ui.mode.textContent, '내 PC');
});

test('unavailable or malformed status stays unknown and never claims private or shared mode', async () => {
  for (const fetchImpl of [async () => { throw new Error('offline'); }, async () => ({ ok: true, json: async () => ({ status: 'ok', public_demo: false }) })]) {
    const ui = setup(fetchImpl);
    assert.deepEqual({ ...(await ui.api.get()) }, { known: false, publicDemo: null });
    ui.listeners.get('DOMContentLoaded')();
    await Promise.resolve(); await Promise.resolve();
    assert.equal(ui.title.textContent, '공무담 업무 공간');
    assert.match(ui.description.textContent, /서버 연결/);
    assert.equal(ui.mode.textContent, '연결 오류');
    assert.doesNotMatch(`${ui.title.textContent} ${ui.description.textContent} ${ui.mode.textContent}`, /내 PC|공개 시연|모든 방문자/);
  }
});
