const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const test = require('node:test');
const assert = require('node:assert/strict');

const root = path.resolve(__dirname, '..');

test('structured guidance can be saved with separate legal and e-Saram evidence', () => {
  const anchors = [];
  const urls = new Map();
  let blobId = 0;
  const box = { children: [], querySelector: () => null, appendChild(node) { this.children.push(node); node.parentNode = this; }, append(...nodes) { nodes.forEach(node => this.appendChild(node)); }, removeChild(node) { this.children = this.children.filter(item => item !== node); } };
  const document = {
    body: { appendChild(node) { node.parentNode = this; }, removeChild(node) {} },
    createElement(tag) {
      const listeners = {};
      const node = { tagName: tag.toUpperCase(), style: {}, attributes: {}, setAttribute(key, value) { this.attributes[key] = value; }, addEventListener(type, callback) { listeners[type] = callback; }, append(...nodes) { this.children = [...(this.children || []), ...nodes]; }, click() { anchors.push({ ...this }); }, remove() {}, _click: () => listeners.click?.() };
      return node;
    }
  };
  const c = {
    window: { setTimeout, URL: { createObjectURL(blob) { const id = `blob:${++blobId}`; urls.set(id, blob); return id; }, revokeObjectURL() {} } },
    document, Blob, URL: { createObjectURL(blob) { const id = `blob:${++blobId}`; urls.set(id, blob); return id; }, revokeObjectURL() {} },
    Intl, Date, Set, Number, String, Array, Object, JSON, Math
  };
  vm.createContext(c);
  vm.runInContext(fs.readFileSync(path.join(root, 'static/answer-record.js'), 'utf8'), c);
  const response = {
    mode: 'structured_guidance', query: '휴가 신청 절차', summary: '등록 자료 기반 안내', answer: '신청 전 확인하세요.',
    guidance: {
      title: '휴가 처리 방법', context: '연가 신청', notice: '실무 준비 제안입니다. 법령 근거를 확인하세요.',
      steps: [{ title: '잔여 일수 확인', detail: '복무 기록 확인' }], questions: ['적용 신분을 확인해 주세요.'],
      deadlines: [{ text: '신청 기한은 기관 기준 확인', ref: 1 }], forms: [{ name: '연가 신청서', href: '/api/documents/doc-1/download', synthetic: true }],
      manual: { evidence: [{ title: 'e-사람 휴가 매뉴얼', page: 27, source_id: 'manual-1', sha256: 'abc123', quote: '휴가 신청 메뉴에서 등록합니다.' }] },
      service_guide: { notice: '공식 제도 설명입니다.', evidence: [{ title: '휴가 FAQ', reference_kind: 'official_faq', quote: 'FAQ 원문 인용', loc: '질문 3', source_url: 'https://www.mpm.go.kr/mpm/info/abc', snapshot_url: '/api/service-guides/faq_3/original', retrieved_at: '2026-10-23', sha256: 'feed123' }] }
    },
    knowledge: { evidence: [{ title: '복무 규정', kind: '규정', loc: '제12조', source_id: 'legal-1', sha256: 'def456', quote: '휴가에 관한 규정 원문입니다.' }] }
  };
  c.window.SeomuAnswerRecord.attach(box, response, { today: '2026-10-24' });
  const actions = box.children[0];
  assert.equal(actions.className, 'answer-record-actions');
  const button = actions.children[1];
  button._click();
  const anchor = anchors[0];
  assert.match(anchor.download, /^seomu-answer-\d+\.txt$/);
  const blob = urls.get(anchor.href);
  assert.ok(blob);
  return blob.text().then(contents => {
    assert.match(contents, /등록 자료 기반 구조화 안내/);
    assert.match(contents, /실무 준비 안내[\s\S]*잔여 일수 확인/);
    assert.match(contents, /법령 근거 1/);
    assert.match(contents, /복무 규정[\s\S]*휴가에 관한 규정 원문입니다/);
    assert.match(contents, /e-사람 사용법 · 등록 매뉴얼 원문/);
    assert.match(contents, /PDF 쪽수: 27[\s\S]*휴가 신청 메뉴에서 등록합니다/);
    assert.match(contents, /인사혁신처 제도 안내·FAQ[\s\S]*휴가 FAQ[\s\S]*질문 3[\s\S]*https:\/\/www\.mpm\.go\.kr\/mpm\/info\/abc[\s\S]*\/api\/service-guides\/faq_3\/original[\s\S]*2026-10-23[\s\S]*feed123[\s\S]*FAQ 원문 인용/);
    assert.match(contents, /국가공무원 제도 설명·FAQ입니다\. 실제 적용과 최신 일수는 법령·기관 기준으로 확인하세요\./);
    assert.equal((contents.match(/\[근거 1\]/g) || []).length, 1);
    assert.doesNotMatch(contents, /\[근거 2\]/);
    assert.doesNotMatch(contents, /모델:/);
  });
});

test('the same answer record can be saved as a 한글 document', async () => {
  const anchors = [], requests = [];
  const box = { children: [], querySelector: () => null, appendChild(node) { this.children.push(node); } };
  const document = {
    body: { appendChild() {} },
    createElement(tag) {
      const listeners = {};
      return { tagName: tag.toUpperCase(), style: {}, setAttribute() {}, addEventListener(type, callback) { listeners[type] = callback; }, append(...nodes) { this.children = [...(this.children || []), ...nodes]; }, click() { anchors.push({ ...this }); }, remove() {}, _click: () => listeners.click?.() };
    }
  };
  const fetch = async (url, init) => { requests.push({ url, init }); return { ok: true, blob: async () => new Blob(['PK']) }; };
  const urls = { createObjectURL: () => 'blob:hwpx', revokeObjectURL() {} };
  const c = { window: { setTimeout, URL: urls }, document, Blob, URL: urls, fetch, Intl, Date, Set, Number, String, Array, Object, JSON, Math };
  vm.createContext(c);
  vm.runInContext(fs.readFileSync(path.join(root, 'static/answer-record.js'), 'utf8'), c);
  c.window.SeomuAnswerRecord.attach(box, { mode: 'source_search', query: '연가는 며칠이야?', summary: '재직기간에 따라 다릅니다.', answer: '원문 답변', knowledge: { evidence: [{ title: '복무 규정', loc: '제15조', quote: '연가 일수 원문' }] } }, { today: '2026-11-03' });
  const hwpx = box.children[0].children[2];
  assert.equal(hwpx.textContent, '한글로 저장');
  await hwpx._click();
  assert.equal(requests[0].url, '/api/exports/hwpx');
  const sent = JSON.parse(requests[0].init.body);
  assert.equal(sent.title, '서무비서 답변 · 연가는 며칠이야?');
  assert.match(sent.text, /재직기간에 따라 다릅니다[\s\S]*복무 규정[\s\S]*연가 일수 원문/);
  assert.match(sent.filename, /^seomu-answer-\d+\.hwpx$/);
  assert.equal(anchors[0].download, sent.filename);
});
