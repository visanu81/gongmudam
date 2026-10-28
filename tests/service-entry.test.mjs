import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../desktop/service-entry.js', import.meta.url), 'utf8');

function setup(href, { framed = false } = {}) {
  const classes = [];
  const replacements = [];
  const location = new URL(href, 'http://localhost:8787/');
  const window = {
    location: { href: location.href, origin: location.origin, pathname: location.pathname, search: location.search, hash: location.hash,
      replace: (value) => replacements.push(value) },
  };
  window.parent = framed ? {} : window;
  const document = { documentElement: { classList: { add: (name) => classes.push(name) } } };
  vm.runInNewContext(source, { window, document, URL });
  return { api: window.GongmudamEntry, replacements, classes };
}

test('direct chat home and start route to the desktop home', () => {
  assert.deepEqual(setup('http://localhost:8787/index.html#home').replacements, ['/desktop/?variant=B']);
  assert.deepEqual(setup('http://localhost:8787/start.html').replacements, ['/desktop/?variant=B']);
});

test('folder project and hash survive routing through desktop open query', () => {
  const route = setup('http://localhost:8787/folders.html?project=alpha#item-2');
  assert.equal(route.replacements[0], '/desktop/?variant=B&open=%2Ffolders.html%3Fproject%3Dalpha%23item-2');
});

test('chat and travel queries are encoded and preserved', () => {
  const chat = setup('http://localhost:8787/index.html?x=1#thread');
  assert.equal(chat.replacements[0], '/desktop/?variant=B&open=%2Findex.html%3Fx%3D1%23thread');
  const travel = setup('http://localhost:8787/travel.html?year=2026#form');
  assert.equal(travel.replacements[0], '/desktop/?variant=B&open=%2Ftravel.html%3Fyear%3D2026%23form');
});

test('all approved services resolve canonically', () => {
  const { api } = setup('http://localhost:8787/desktop/');
  const routes = {
    '/index.html': 'chat', '/travel.html': 'travel', '/adhoc.html': 'collection',
    '/folders.html': 'folders', '/folders-advanced.html': 'folders', '/toolbox.html': 'toolbox',
    '/change-inbox.html': 'inbox', '/calendar.html': 'calendar', '/local-ai.html': 'models',
  };
  for (const [href, id] of Object.entries(routes)) assert.deepEqual({ ...api.resolveService(href) }, { id, href });
});

test('iframes and desktop paths never auto redirect', () => {
  assert.deepEqual(setup('http://localhost:8787/folders.html', { framed: true }).replacements, []);
  const desktop = setup('http://localhost:8787/desktop/?variant=B');
  assert.deepEqual(desktop.replacements, []);
  assert.equal(desktop.api.desktopHref('http://localhost:8787/desktop/'), null);
});

test('unknown paths, foreign origins, and unsafe or malformed URLs are rejected', () => {
  const { api } = setup('http://localhost:8787/desktop/');
  for (const href of ['https://evil.test/folders.html', '//evil.test/folders.html', 'javascript:alert(1)',
    '/unknown.html', '/folders.html%2f..%2funknown', 'http://[broken']) {
    assert.equal(api.resolveService(href), null, href);
    assert.equal(api.desktopHref(href), null, href);
  }
});
