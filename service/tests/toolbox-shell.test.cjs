const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'static/toolbox.html'), 'utf8');
const appSource = fs.readFileSync(path.join(root, 'static/toolbox/app.js'), 'utf8');

function rootElementCount(markup) {
  const match = markup.match(/<section\b(?=[^>]*\bid=["']toolbox-app["'])[^>]*>([\s\S]*?)<\/section>/i);
  assert.ok(match, 'toolbox-app root exists in shipped HTML');
  let depth = 0; let count = 0;
  for (const token of match[1].matchAll(/<!--[\s\S]*?-->|<\/?[a-z][^>]*>|[^<]+/gi)) {
    const value = token[0];
    if (value.startsWith('<!--') || !value.startsWith('<')) continue;
    if (/^<\//.test(value)) depth--;
    else if (!/^<[^>]+\/\s*>$/.test(value)) { if (depth === 0) count++; depth++; }
    else if (depth === 0) count++;
  }
  return count;
}

class Element {
  constructor(tag = 'div', className = '') {
    this.nodeType = 1; this.tagName = tag.toUpperCase(); this.className = className;
    this.children = []; this.listeners = {}; this.style = {}; this.attributes = {};
  }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; }
  addEventListener(type, fn) { this.listeners[type] = fn; }
  setAttribute(name, value) { this.attributes[name] = value; }
  get childElementCount() { return this.children.filter((child) => child.nodeType === 1).length; }
}

function bootWithMarkup(markup) {
  const appRoot = new Element('section');
  for (let i = 0; i < rootElementCount(markup); i++) appRoot.append(new Element('p', 'placeholder'));
  const ids = {
    'toolbox-app': appRoot,
    band: new Element('div'),
    count: new Element('span'),
  };
  const document = {
    getElementById: (id) => ids[id] || null,
    createElement: (tag) => new Element(tag),
    createTextNode: (text) => ({ nodeType: 3, textContent: String(text) }),
    querySelector: () => null,
    body: new Element('body'),
  };
  const window = { addEventListener() {}, scrollTo() {} };
  const context = { window, document, location: { hash: '', pathname: '/toolbox.html', search: '' },
    history: { state: null, replaceState() {}, pushState() {}, back() {} },
    URL, Blob, File: class File {}, setTimeout, clearTimeout, console };
  vm.createContext(context);
  vm.runInContext(appSource, context);
  context.window.App.add({ id: 'synthetic-admin', cat: 'admin', code: 'TEST', name: '회귀 도구', desc: 'bootstrap 렌더링 확인', render() {} });
  context.window.App.start();
  return appRoot;
}

function containsTile(node) {
  return node.className === 'tile' || node.children.some((child) => child.nodeType === 1 && containsTile(child));
}

test('shipped empty toolbox root bootstraps admin tiles; a placeholder child suppresses the initial render', () => {
  const actualRoot = bootWithMarkup(html);
  assert.equal(rootElementCount(html), 0, 'the actual toolbox-app starts with no element children');
  assert.equal(containsTile(actualRoot), true, 'App.start renders the registered admin tool into the shipped empty root');

  const withPlaceholder = html.replace(/(<section id="toolbox-app"[^>]*>)(<\/section>)/, '$1<p>placeholder</p>$2');
  assert.equal(rootElementCount(withPlaceholder), 1, 'the simulated placeholder is reflected in the parsed initial DOM');
  assert.equal(containsTile(bootWithMarkup(withPlaceholder)), false, 'the actual bootstrap guard leaves placeholder content and skips home rendering');
});
