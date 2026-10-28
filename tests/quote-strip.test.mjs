import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';

const source = fs.readFileSync(new URL('../desktop/quote-strip.js', import.meta.url), 'utf8');
class Element {
  constructor() { this.textContent = ''; this.attributes = new Map(); this.listeners = new Map(); this.children = new Map(); }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  removeAttribute(name) { this.attributes.delete(name); }
  hasAttribute(name) { return this.attributes.has(name); }
  addEventListener(name, listener) { this.listeners.set(name, listener); }
  removeEventListener(name) { this.listeners.delete(name); }
  querySelector(selector) { return this.children.get(selector) || null; }
  click() { this.listeners.get('click')?.(); }
}
class FakeClock {
  now = 0;
  nextId = 1;
  tasks = new Map();
  setTimeout = (callback, delay) => { const id = this.nextId++; this.tasks.set(id, { callback, due: this.now + delay }); return id; };
  clearTimeout = id => this.tasks.delete(id);
  tick(ms) {
    const end = this.now + ms;
    while (true) {
      const next = [...this.tasks.entries()].sort((a, b) => a[1].due - b[1].due)[0];
      if (!next || next[1].due > end) break;
      this.now = next[1].due; this.tasks.delete(next[0]); next[1].callback();
    }
    this.now = end;
  }
}
function fixture({ storage, getStorage } = {}) {
  const clock = new FakeClock(), visibility = new Map();
  const document = { hidden: false, addEventListener: (name, fn) => visibility.set(name, fn), removeEventListener: name => visibility.delete(name) };
  const quote = new Element(); quote.textContent = '오늘의 작은 정리가 내일의 여유를 만듭니다.';
  const next = new Element(), toggle = new Element(), pauseIcon = new Element(), playIcon = new Element();
  playIcon.setAttribute('hidden', '');
  toggle.children.set('[data-quote-icon="pause"]', pauseIcon); toggle.children.set('[data-quote-icon="play"]', playIcon);
  const root = { ownerDocument: document, querySelector: selector => ({ '#header-quote-text': quote, '#header-quote-next': next, '#header-quote-toggle': toggle })[selector] || null };
  const values = storage || new Map();
  const store = {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
  };
  let fetchCalls = 0;
  const window = { fetch: () => { fetchCalls += 1; throw new Error('network must not be used'); } };
  vm.runInNewContext(source, { window });
  const controller = window.GongmudamQuoteStrip.init({ root, document, getStorage: getStorage || (() => store), setTimeout: clock.setTimeout, clearTimeout: clock.clearTimeout });
  return { clock, controller, document, fetchCalls: () => fetchCalls, next, pauseIcon, playIcon, quote, toggle, values, visibility };
}

test('rotates after 45 seconds and manual next restarts the full interval', () => {
  const f = fixture();
  f.clock.tick(44_999); assert.equal(f.quote.textContent, '오늘의 작은 정리가 내일의 여유를 만듭니다.');
  f.clock.tick(1); assert.equal(f.quote.textContent, '중요한 일은 기억보다 기록에 맡겨두세요.');
  f.clock.tick(20_000); f.next.click();
  assert.equal(f.quote.textContent, '한꺼번에 끝내려 하기보다, 다음 한 단계부터.');
  f.clock.tick(44_999); assert.equal(f.quote.textContent, '한꺼번에 끝내려 하기보다, 다음 한 단계부터.');
  f.clock.tick(1); assert.equal(f.quote.textContent, '함께 확인한 기준은 더 믿음직한 업무가 됩니다.');
  f.controller.dispose();
});

test('pause persists, updates its accessible state, and resume starts a full interval', () => {
  const f = fixture();
  f.toggle.click();
  assert.equal(f.toggle.getAttribute('aria-pressed'), 'true');
  assert.equal(f.toggle.getAttribute('aria-label'), '문구 자동 변경 시작');
  assert.equal(f.pauseIcon.hasAttribute('hidden'), true); assert.equal(f.playIcon.hasAttribute('hidden'), false);
  assert.equal(f.values.get('gongmudam.header-quote.paused.v1'), 'true');
  f.clock.tick(90_000); assert.equal(f.quote.textContent, '오늘의 작은 정리가 내일의 여유를 만듭니다.');
  f.toggle.click();
  assert.equal(f.toggle.getAttribute('aria-pressed'), 'false');
  assert.equal(f.toggle.getAttribute('aria-label'), '문구 자동 변경 멈춤');
  f.clock.tick(44_999); assert.equal(f.quote.textContent, '오늘의 작은 정리가 내일의 여유를 만듭니다.');
  f.clock.tick(1); assert.equal(f.quote.textContent, '중요한 일은 기억보다 기록에 맡겨두세요.');
  f.controller.dispose();
});

test('a new instance restores a saved paused preference', () => {
  const values = new Map([['gongmudam.header-quote.paused.v1', 'true']]);
  const f = fixture({ storage: values });
  assert.equal(f.toggle.getAttribute('aria-pressed'), 'true');
  assert.equal(f.toggle.getAttribute('aria-label'), '문구 자동 변경 시작');
  assert.equal(f.pauseIcon.hasAttribute('hidden'), true); assert.equal(f.playIcon.hasAttribute('hidden'), false);
  assert.equal(f.clock.tasks.size, 0);
  f.controller.dispose();
});

test('hidden documents suspend rotation and visibility resumes a full 45-second interval', () => {
  const f = fixture();
  f.clock.tick(20_000); f.document.hidden = true; f.visibility.get('visibilitychange')();
  f.clock.tick(90_000); assert.equal(f.quote.textContent, '오늘의 작은 정리가 내일의 여유를 만듭니다.');
  f.document.hidden = false; f.visibility.get('visibilitychange')();
  f.clock.tick(44_999); assert.equal(f.quote.textContent, '오늘의 작은 정리가 내일의 여유를 만듭니다.');
  f.clock.tick(1); assert.equal(f.quote.textContent, '중요한 일은 기억보다 기록에 맡겨두세요.');
  f.controller.dispose();
});

test('blocked storage is harmless and rotation makes no network requests', () => {
  const f = fixture({ getStorage: () => { throw new Error('storage blocked'); } });
  assert.doesNotThrow(() => f.toggle.click());
  assert.doesNotThrow(() => f.toggle.click());
  f.clock.tick(45_000);
  assert.equal(f.quote.textContent, '중요한 일은 기억보다 기록에 맡겨두세요.');
  assert.equal(f.fetchCalls(), 0);
  f.controller.dispose();
});
