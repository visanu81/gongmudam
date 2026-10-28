import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../desktop/service-bridge.js', import.meta.url), 'utf8');

function setup(options = {}) {
  const listeners = new Map();
  const timers = new Map();
  let timerId = 0;
  class Element {
    constructor(tag) { this.tag = tag; this.children = []; this.listeners = new Map(); this.dataset = {}; this.hidden = false; }
    setAttribute(key, value) { this[key] = value; }
    append(...children) { this.children.push(...children); }
    addEventListener(type, fn) { this.listeners.set(type, fn); }
    removeEventListener(type, fn) { if (this.listeners.get(type) === fn) this.listeners.delete(type); }
    remove() { this.removed = true; }
  }
  const window = {
    addEventListener: (type, fn) => listeners.set(type, fn),
    removeEventListener: (type, fn) => { if (listeners.get(type) === fn) listeners.delete(type); },
    setTimeout: (fn) => { const id = ++timerId; timers.set(id, fn); return id; },
    clearTimeout: (id) => timers.delete(id),
  };
  const context = { window, location: { origin: 'https://example.test' }, URL, Date, Math, globalThis: { crypto: { randomUUID: () => 'question-1' } },
    document: { createElement: (tag) => new Element(tag) },
    clearTimeout: window.clearTimeout,
  };
  vm.runInNewContext(source, context);
  const body = new Element('body'); body.classList = { add: () => {} };
  const bridge = window.GongmudamServiceBridge.mount(body, 'chat', options);
  const shell = body.children[0]; const frame = shell.children[1]; const toolbar = shell.children[0];
  return { bridge, frame, shell, toolbar, listeners, timers, runTimer() { [...timers.values()][0]?.(); } };
}

test('home messages retain the frame and delegate only from the trusted ready child', () => {
  let returned = 0;
  const {frame, toolbar, listeners} = setup({onHome: () => returned++});
  frame.contentWindow = {postMessage() {}};
  const onMessage = listeners.get('message');
  const home = {source:frame.contentWindow, origin:'https://example.test', data:{type:'gongmudam:home'}};
  onMessage(home); assert.equal(returned,0);
  onMessage({...home,data:{type:'gongmudam:ready'}});
  onMessage({...home,origin:'https://evil.test'}); assert.equal(returned,0);
  onMessage(home); assert.equal(returned,1);
  assert.equal(frame.hidden,false);
  assert.equal(toolbar.children[2].href,'/desktop/?variant=B&open=%2Findex.html%23chat');
});

test('frame stays hidden through initial load, navigation, and retry until valid ready', () => {
  const { bridge, frame, shell, toolbar } = setup();
  assert.equal(frame.hidden, true);
  assert.equal(shell['aria-busy'], 'true');
  assert.equal(toolbar.children[1].hidden, true);
  bridge.navigate('/travel.html');
  assert.equal(frame.hidden, true);
  frame.listeners.get('load')();
  assert.equal(frame.hidden, true);
  toolbar.children[1].listeners.get('click')();
  assert.equal(frame.hidden, true);
});

test('only a same-origin message from this frame reveals it and flushes queued question', () => {
  const { bridge, frame, listeners } = setup();
  bridge.ask('hello');
  const onMessage = listeners.get('message');
  onMessage({ source: {}, origin: 'https://example.test', data: { type: 'gongmudam:ready' } });
  onMessage({ source: frame.contentWindow, origin: 'https://evil.test', data: { type: 'gongmudam:ready' } });
  assert.equal(frame.hidden, true);
  frame.contentWindow = { messages: [], postMessage(message) { this.messages.push(message); } };
  onMessage({ source: frame.contentWindow, origin: 'https://example.test', data: { type: 'gongmudam:ready' } });
  assert.equal(frame.hidden, false);
  assert.equal(frame.contentWindow.messages.some((m) => m.type === 'gongmudam:question' && m.text === 'hello'), true);
});

test('timeout leaves the frame hidden with retry available and clears busy; retry resumes busy state', () => {
  const { bridge, frame, shell, toolbar, timers, listeners, runTimer } = setup();
  runTimer();
  assert.equal(frame.hidden, true);
  assert.equal(toolbar.children[1].hidden, false);
  assert.equal(shell['aria-busy'], 'false');
  toolbar.children[1].listeners.get('click')();
  assert.equal(shell['aria-busy'], 'true');
  assert.equal(frame.hidden, true);
  bridge.dispose();
  assert.equal(listeners.has('message'), false);
  assert.equal(timers.size, 0);
  assert.equal(frame.src, 'about:blank');
});

test('late load after timeout preserves failure controls until trusted ready or retry', () => {
  const first = setup();
  first.runTimer();
  first.frame.listeners.get('load')();
  assert.equal(first.frame.hidden, true);
  assert.equal(first.shell['aria-busy'], 'false');
  assert.equal(first.toolbar.children[1].hidden, false);
  first.frame.contentWindow = { postMessage() {} };
  first.listeners.get('message')({ source: first.frame.contentWindow, origin: 'https://example.test', data: { type: 'gongmudam:ready' } });
  assert.equal(first.frame.hidden, false);
  assert.equal(first.toolbar.children[1].hidden, true);
  first.bridge.dispose();

  const second = setup();
  second.runTimer();
  second.frame.listeners.get('load')();
  second.toolbar.children[1].listeners.get('click')();
  assert.equal(second.frame.hidden, true);
  assert.equal(second.shell['aria-busy'], 'true');
  assert.equal(second.toolbar.children[1].hidden, true);
  second.bridge.dispose();
});
