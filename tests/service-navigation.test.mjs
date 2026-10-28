import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';

const source = fs.readFileSync(new URL('../desktop/desktop.js', import.meta.url), 'utf8');
const openAppSource = source.slice(source.indexOf('function openApp('), source.indexOf('function openHomeAgenda'));
const onOpenSource = source.match(/onOpen:\s*(\([^\n]+\)\s*=>\s*openApp\([^\n]+\))/)?.[1];
assert.ok(onOpenSource, 'extract desktop mount onOpen callback');

function fixture() {
  const calls = [], activations = [];
  const state = { window: { hidden: false }, serviceHref: '/index.html?rule=abc#docs', service: { navigate: href => calls.push(href) } };
  const windows = new Map([['chat', state]]);
  const apps = new Map([['chat', { id: 'chat' }]]);
  const serviceRoutes = { chat: '/index.html' };
  const document = { querySelector: () => ({ setAttribute() {} }) };
  const context = { apps, serviceRoutes, windows, document, makeWindow() { throw new Error('unexpected window creation'); }, activate: (...args) => activations.push(args) };
  vm.runInNewContext(`${openAppSource}\nthis.openApp = openApp; this.onOpen = ${onOpenSource};`, context);
  return { ...context, state, calls, activations };
}

test('manager callback forces navigation even when cached href matches after child route changes', () => {
  const f = fixture();
  // The iframe navigated itself to chat; the parent's remembered manager href is unchanged.
  f.onOpen('chat', '/index.html?rule=abc#docs');
  f.onOpen('chat', '/index.html?rule=abc#docs');
  assert.deepEqual(f.calls, ['/index.html?rule=abc#docs', '/index.html?rule=abc#docs']);
});

test('ordinary openApp reuses the cached destination and forced destination preserves query', () => {
  const f = fixture();
  f.openApp('chat', '/index.html?rule=abc#docs');
  assert.deepEqual(f.calls, []);
  f.openApp('chat', '/index.html?rule=other#section', null, true);
  assert.deepEqual(f.calls, ['/index.html?rule=other#section']);
});
