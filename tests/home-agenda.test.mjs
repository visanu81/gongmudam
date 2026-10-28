import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';
const source = fs.readFileSync(new URL('../desktop/home-agenda.js', import.meta.url), 'utf8');
function fixture(fetcher = async () => ({ ok: true, json: async () => snapshot([]) })) {
  const listeners = new Map();
  const document = { hidden: false, activeElement: null, addEventListener: (k, v) => listeners.set(k, v), removeEventListener: k => listeners.delete(k) };
  class Node {
    constructor(tag) { this.tag = tag; this.children = []; this.attributes = {}; this.listeners = {}; this.ownText = ''; }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = children; this.ownText = ''; }
    set textContent(v) { this.ownText = v; this.children = []; }
    get textContent() { return this.ownText + this.children.map(v => v.textContent).join(''); }
    setAttribute(k, v) { this.attributes[k] = v; }
    getAttribute(k) { return this.attributes[k] || null; }
    addEventListener(k, v) { this.listeners[k] = v; }
    contains(v) { return this === v || this.children.some(n => n.contains(v)); }
    querySelectorAll() { return this.children.flatMap(n => [n, ...n.querySelectorAll()]).filter(n => n.attributes['data-home-focus']); }
    focus() { document.activeElement = this; }
  }
  document.createElement = tag => new Node(tag);
  const window = { location: { origin: 'https://app.test' }, fetch: fetcher, setInterval: () => 1, clearInterval() {},
    addEventListener: (k, v) => listeners.set(k, v), removeEventListener: k => listeners.delete(k) };
  vm.runInNewContext(source, { window, document, URL, URLSearchParams, Date, AbortController });
  const root = new Node('section'), opened = [];
  const api = window.GongmudamHomeAgenda;
  return { api, root, document, opened, listeners, start: () => api.mount({ root, open: (...args) => opened.push(args), fetcher }) };
}
function snapshot(tasks) { return { today: '2027-01-01', week_start: '2026-12-28', week_end: '2027-01-03', tasks }; }
function row(id, due = '2027-01-01', extra = {}) { return { id, due, title: id, work_title: '합성 교육', status: 'todo', status_label: '미완료', is_task: true, is_deadline: true, action: { type: 'education', job_id: 'job1', step_id: id }, ...extra }; }
const flush = () => new Promise(resolve => setImmediate(resolve));
const reply = tasks => ({ ok: true, json: async () => snapshot(tasks) });
function button(root, key) { return root.querySelectorAll().find(n => n.getAttribute('data-home-focus') === key); }

test('today and Monday–Sunday deadlines use server KST dates across the year boundary', () => {
  const { api } = fixture();
  const selected = api.select(snapshot([row('today'), row('last-year', '2026-12-31', { overdue: true }), row('done', undefined, { status: 'done' }),
    row('undated', null), row('appointment', undefined, { is_task: false, is_deadline: false }), row('next-week', '2027-01-04'), row('bad-date', '2027-02-30')]));
  assert.deepEqual(Array.from(selected.today, r => r.id), ['today']);
  assert.deepEqual(Array.from(selected.week, r => r.id), ['last-year', 'today']);
  assert.equal(selected.next.id, 'next-week');
  assert.throws(() => api.select({ ...snapshot([]), today: '2027-02-30' }));
  assert.throws(() => api.select({ ...snapshot([]), tasks: null }));
});

test('education links retain the exact stage; arbitrary destinations fall back to the dated calendar', () => {
  const { api } = fixture();
  const destination = api.destination(row('a', '2027-01-01', { action: { type: 'education', job_id: 'job/a&b', step_id: 'step c' } }), 'https://app.test');
  assert.equal(destination.id, 'collection');
  assert.equal(destination.href, '/adhoc.html?step=step%20c#job-job%2Fa%26b');
  for (const href of ['https://evil.test/adhoc.html', '//evil.test/travel.html', 'javascript:alert(1)', '/unknown.html']) {
    const target = api.destination(row('a', undefined, { action: { type: 'link', href } }), 'https://app.test');
    assert.equal(target.id, 'calendar'); assert.match(target.href, /date=2027-01-01/);
  }
  const trip = api.destination(row('a', undefined, { action: { type: 'link', href: 'travel.html?case=abc#settle' } }), 'https://app.test');
  assert.equal(trip.id, 'travel'); assert.equal(trip.href, '/travel.html?case=abc#settle');
  assert.equal(api.destination(row('a', undefined, { action: { type: 'manual' } }), 'https://app.test').id, 'calendar');
});

test('rendered task and more buttons open the stage and current week; focus survives a refresh', async () => {
  const f = fixture(async () => reply([row('one'), row('two', '2027-01-02'), row('three', '2027-01-03')]));
  const controller = f.start(); await flush();
  assert.match(f.root.textContent, /오늘 할 일 1/); assert.match(f.root.textContent, /이번 주 마감 3/);
  button(f.root, 'today:one').listeners.click();
  assert.deepEqual(f.opened[0], ['collection', '/adhoc.html?step=one#job-job1']);
  button(f.root, 'more:week').listeners.click();
  assert.equal(f.opened[1][0], 'calendar'); assert.match(f.opened[1][1], /date=2027-01-01&view=timeGridWeek/);
  button(f.root, 'today:one').focus(); await controller.refresh();
  assert.equal(f.document.activeElement.getAttribute('data-home-focus'), 'today:one');
  controller.dispose(); assert.equal(f.listeners.size, 0);
});

test('older responses never replace the latest result, including when fetch ignores abort', async () => {
  const pending = [], f = fixture(() => new Promise(resolve => pending.push(resolve)));
  const controller = f.start();
  const newest = controller.refresh(); pending[1](reply([row('latest')])); await newest;
  pending[0](reply([row('old')])); await flush();
  assert.ok(button(f.root, 'today:latest')); assert.equal(button(f.root, 'today:old'), undefined);
  controller.dispose();
});

test('failure is distinct from zero tasks; stale results are labelled and completion removes a task', async () => {
  let mode = 'fail';
  const f = fixture(async () => { if (mode === 'fail') throw new Error('offline'); return reply(mode === 'data' ? [row('task')] : []); });
  const controller = f.start(); await flush();
  assert.match(f.root.textContent, /업무를 불러오지 못했습니다/); assert.doesNotMatch(f.root.textContent, /오늘 할 일 0/);
  mode = 'data'; await controller.refresh(); assert.ok(button(f.root, 'today:task'));
  mode = 'fail'; await controller.refresh();
  assert.match(f.root.textContent, /이전 결과/); assert.ok(button(f.root, 'today:task'));
  mode = 'empty'; await controller.refresh();
  assert.match(f.root.textContent, /오늘 할 일 0/); assert.equal(button(f.root, 'today:task'), undefined);
  controller.dispose();
});

test('a quiet week still offers the next actual deadline and midnight visibility refresh uses the new date', async () => {
  let value = snapshot([row('future', '2027-01-04')]);
  const f = fixture(async () => ({ ok: true, json: async () => value }));
  const controller = f.start(); await flush();
  button(f.root, 'next:future').listeners.click(); assert.match(f.opened[0][1], /step=future/);
  value = { today: '2027-01-04', week_start: '2027-01-04', week_end: '2027-01-10', tasks: [row('future', '2027-01-04')] };
  f.listeners.get('visibilitychange')(); await flush();
  assert.match(f.root.textContent, /2027.01.04/); assert.ok(button(f.root, 'today:future'));
  controller.dispose();
});

test('focus refresh keeps unchanged task buttons alive so the first click is not cancelled', async () => {
  const f = fixture(async () => reply([row('stable')]));
  const controller = f.start(); await flush();
  const original = button(f.root, 'today:stable');
  f.listeners.get('focus')();
  assert.equal(button(f.root, 'today:stable'), original, 'pending refresh retains the click target');
  await flush();
  assert.equal(button(f.root, 'today:stable'), original, 'unchanged response retains the click target');
  original.listeners.click(); assert.equal(f.opened.length, 1);
  controller.dispose();
});

test('home agenda forces its destination while ordinary app activation keeps the current service page', () => {
  const desktopSource = fs.readFileSync(new URL('../desktop/desktop.js', import.meta.url), 'utf8');
  function functionText(name) {
    const start = desktopSource.indexOf(`function ${name}(`);
    assert.notEqual(start, -1, `${name} exists`);
    const open = desktopSource.indexOf('{', start);
    let depth = 0;
    for (let i = open; i < desktopSource.length; i += 1) {
      if (desktopSource[i] === '{') depth += 1;
      if (desktopSource[i] === '}' && --depth === 0) return desktopSource.slice(start, i + 1);
    }
    assert.fail(`${name} has a closing brace`);
  }
  const navigations = [], activations = [];
  const state = { id: 'calendar', serviceHref: '/calendar.html?date=2027-01-01', serviceItemId: null,
    service: { currentHref: '/calendar.html?date=2027-01-02', navigate: href => { navigations.push(href); } } };
  const context = {
    apps: new Map([['calendar', { id: 'calendar' }]]), serviceRoutes: {}, windows: new Map([['calendar', state]]),
    makeWindow: () => assert.fail('existing calendar window is reused'), activate: value => activations.push(value),
    document: { querySelector: () => ({ setAttribute() {} }) }, window: {},
  };
  vm.runInNewContext(`${functionText('openApp')}\n${functionText('openHomeAgenda')}\nwindow.openApp = openApp; window.openHomeAgenda = openHomeAgenda;`, context);
  context.window.openHomeAgenda('calendar', '/calendar.html?date=2027-01-01');
  assert.deepEqual(navigations, ['/calendar.html?date=2027-01-01']);
  context.window.openApp('calendar');
  assert.deepEqual(navigations, ['/calendar.html?date=2027-01-01']);
  assert.deepEqual(activations, [state, state]);
});

test('icon clamp reserves the agenda shelf on desktop, not on narrow screens', () => {
  const desktopSource = fs.readFileSync(new URL('../desktop/desktop.js', import.meta.url), 'utf8');
  const start = desktopSource.indexOf('function clampIconPosition(');
  assert.notEqual(start, -1, 'clampIconPosition exists');
  const open = desktopSource.indexOf('{', start);
  let depth = 0, end = -1;
  for (let i = open; i < desktopSource.length; i += 1) {
    if (desktopSource[i] === '{') depth += 1;
    if (desktopSource[i] === '}' && --depth === 0) { end = i + 1; break; }
  }
  assert.notEqual(end, -1, 'clampIconPosition has a closing brace');
  const clampSource = `${desktopSource.slice(start, end)}\nwindow.clampIconPosition = clampIconPosition;`;
  function clamp(width, shelfLeft, shelfWidth, requestedLeft) {
    const area = { getBoundingClientRect: () => ({ left: 0, width, height: 700 }) };
    const button = { getBoundingClientRect: () => ({ width: 100, height: 100 }), offsetWidth: 100, offsetHeight: 100 };
    const document = { querySelector: () => ({ getBoundingClientRect: () => ({ left: shelfLeft, width: shelfWidth }) }) };
    const window = {};
    vm.runInNewContext(clampSource, { area, button, document, window });
    return window.clampIconPosition(button, { left: requestedLeft, top: 20 });
  }
  const mobile = clamp(390, 12, 366, 200);
  assert.equal(mobile.left, 200); assert.equal(mobile.top, 20);
  const desktop = clamp(1280, 880, 350, 1000);
  assert.equal(desktop.left, 764); assert.equal(desktop.top, 20);
});
