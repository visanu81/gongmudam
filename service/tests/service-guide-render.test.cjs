const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const test = require('node:test');
const assert = require('node:assert/strict');

const root = path.resolve(__dirname, '..');

function render(guidance, evidence = [{ title: '법령' }]) {
  const box = { children: [], querySelector: () => null, prepend(node) { this.children.unshift(node); } };
  const document = { createElement(tag) { return { tagName: tag.toUpperCase(), className: '', querySelectorAll: () => [], set innerHTML(value) { this.html = value; }, get innerHTML() { return this.html; } }; } };
  const context = { window: {}, document, URL, String, Array, Set, Number, Object };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(root, 'static/guidance-ui.js'), 'utf8'), context);
  context.window.SeomuGuidance.render(box, { guidance, knowledge: { evidence } });
  return box.children[0]?.innerHTML || '';
}

test('service guide quotes are escaped and only approved URLs become links', () => {
  const html = render({ service_guide: { evidence: [
    { title: 'FAQ', reference_kind: 'official_faq', quote: '<script>alert(1)</script>', loc: '질문 1', retrieved_at: '2026-10-23', source_url: 'https://www.mpm.go.kr/mpm/info/faq', snapshot_url: '/api/service-guides/faq_1/original' },
    { title: 'Untrusted', reference_kind: 'official_faq', quote: 'bad links', source_url: 'javascript:alert(1)', snapshot_url: 'https://evil.example/api/service-guides/x/original' },
    { title: 'Credentialed', reference_kind: 'official_service_guide', quote: 'bad host', source_url: 'https://user:pass@evil.example/mpm/info/x', snapshot_url: '/api/service-guides/x/original?raw=1' }
  ] } });
  assert.match(html, /인사혁신처 제도 안내·FAQ/);
  assert.match(html, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.doesNotMatch(html, /<blockquote><script>/);
  assert.match(html, /href="https:\/\/www\.mpm\.go\.kr\/mpm\/info\/faq"/);
  assert.match(html, /href="\/api\/service-guides\/faq_1\/original"/);
  assert.doesNotMatch(html, /href="javascript:/);
  assert.doesNotMatch(html, /href="https:\/\/evil\.example/);
  assert.doesNotMatch(html, /href="\/api\/service-guides\/x\/original/);
});

test('service guide section is omitted when evidence is absent', () => {
  const html = render({ service_guide: { notice: 'notice only', evidence: [] } });
  assert.doesNotMatch(html, /인사혁신처 제도 안내·FAQ/);
});

test('institution scope labels validated organization names and escapes supplied text', () => {
  const affiliation = render({ institution_scope: { basis: 'affiliation', organizations: ['서울시 <청사>', 4, '', '부서 & 기관'] } });
  assert.match(affiliation, /내 소속 기준: 서울시 &lt;청사&gt;, 부서 &amp; 기관/);
  assert.doesNotMatch(affiliation, /<청사>|, 4/);

  const question = render({ institution_scope: { basis: 'question', organizations: ['가람시'] } });
  assert.match(question, /질문에서 지정한 기관: 가람시/);
});

test('missing or malformed institution scope leaves the guidance heading unchanged', () => {
  for (const scope of [undefined, null, '서울시', { basis: 'other', organizations: ['기관'] }, { basis: 'question', organizations: '기관' }, { basis: 'affiliation', organizations: [null, 3] }]) {
    const html = render({ title: '업무 안내', institution_scope: scope });
    assert.match(html, /<h2>업무 안내<\/h2>/);
    assert.doesNotMatch(html, /내 소속 기준:|질문에서 지정한 기관:/);
  }
});

test('institution rule evidence replaces generic preparation and empty-deadline copy only for institution guidance', () => {
  const rule = { title: '기관 복무 규정', reference_kind: 'institution_rule' };
  const institutionHtml = render({ topic: 'institution', steps: [], deadlines: [] }, [rule]);
  assert.match(institutionHtml, /현재 적용된 상태인지 확인/);
  assert.match(institutionHtml, /답변에 적용된 버전과 인용된 원문 발췌를 대조/);
  assert.match(institutionHtml, /기관 자료의 기한은 위 원문 발췌와 적용 조건에서 확인하세요\. 별도 기한 판정은 제공하지 않습니다\./);
  assert.doesNotMatch(institutionHtml, /정확한 기한을 확인할 등록 근거가 부족해요/);

  const otherTopicHtml = render({ topic: 'leave', steps: [], deadlines: [] }, [rule]);
  assert.match(otherTopicHtml, /등록된 처리 순서가 없습니다/);
  assert.match(otherTopicHtml, /정확한 기한을 확인할 등록 근거가 부족해요/);
});

test('managed institution forms link only to the local original and derive a fixed manager link', () => {
  const doc = 'a'.repeat(32);
  const version = 'b'.repeat(32);
  const html = render({ forms: [
    { name: '신청서', kind: '서식', reference_kind: 'institution_rule', version_number: 2, href: `/api/institution-rules/${doc}/versions/${version}/original`, manager_href: `index.html?rule=${doc}&rule_version=${version}#docs` },
    { name: '나쁜 주소', kind: '서식', reference_kind: 'institution_rule', version_number: 3, href: 'https://evil.example/steal', manager_href: 'javascript:alert(1)' },
    { name: '경로 변조', kind: '서식', reference_kind: 'institution_rule', version_number: 4, href: `/api/institution-rules/${doc}/versions/../original` },
    { name: '기존 서식', href: 'index.html#forms' }
  ] });
  assert.match(html, new RegExp(`<a href="/api/institution-rules/${doc}/versions/${version}/original" target="_blank" rel="noopener noreferrer">신청서 · 서식 · v2</a>`));
  assert.match(html, new RegExp(`<a href="index.html\\?rule=${doc}&amp;rule_version=${version}#docs">관리</a>`));
  assert.doesNotMatch(html, /evil\.example|javascript:alert|versions\/\.\./);
  assert.match(html, /기존 서식/);
});
