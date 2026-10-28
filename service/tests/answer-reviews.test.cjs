const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'static', 'answer-reviews.js'), 'utf8');
const html = fs.readFileSync(path.join(__dirname, '..', 'static', 'index.html'), 'utf8');
function hooks() {
  const context = {
    document: { querySelector: () => ({}) },
    window: { __SEOMU_TEST__: true },
    URLSearchParams,
    Date,
    Map,
    Set,
    String,
    Number,
    Object,
    JSON
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  return context.window.SeomuAnswerReview.testHooks;
}

test('apply confirmation is bound to the exact saved draft', () => {
  const { confirmationKey, isConfirmed } = hooks();
  const detail = { id: 'review-1', draft_version_id: 'v2', active_version_id: 'v1', versions: [{ id: 'v1', number: 1 }, { id: 'v2', number: 2 }] };
  const reviewedConfirmation = confirmationKey(detail);
  assert.equal(reviewedConfirmation, 'review-1:v2');
  assert.equal(isConfirmed(reviewedConfirmation, detail), true);
  detail.draft_version_id = 'v3';
  detail.versions.push({ id: 'v3', number: 3 });
  assert.equal(isConfirmed(reviewedConfirmation, detail), false);
  assert.match(source, /if \(!isConfirmed\(state\.confirmed, d\)\)/);
  assert.match(source, /state\.confirmed = e\.target\.checked \? confirmedKey\(state\.detail\) : null/);
  assert.match(source, /state\.confirmed = null; state\.dirty = !!state\.edits\[selectedAtStart\]/);
});

test('source selections distinguish units and retain saved draft references when resaving', () => {
  const { mergeEvidence } = hooks();
  const saved = [
    { source_id: 'same-source', unit_index: 0, sha256: 'abc', quote: 'first' },
    { source_id: 'same-source', unit_index: 1, sha256: 'abc', quote: 'second' },
    { source_id: 'other-source', unit_index: 0, sha256: 'def', quote: 'hidden search result' }
  ];
  const edited = mergeEvidence(saved, [
    { checked: true, reference: { source_id: 'same-source', unit_index: 0, sha256: 'abc', quote: 'updated first' } },
    { checked: false, reference: { source_id: 'same-source', unit_index: 1, sha256: 'abc', quote: 'second' } }
  ]);
  assert.deepEqual(JSON.parse(JSON.stringify(edited)), [saved[2], { ...saved[0], quote: 'updated first' }]);
  assert.deepEqual(JSON.parse(JSON.stringify(mergeEvidence(saved, []))), saved);
  assert.match(source, /e\.source_id === s\.source_id && Number\(e\.unit_index\) === Number\(s\.unit_index\)/);
  assert.match(source, /candidateMap\.set\(`\$\{e\.source_id\}:\$\{Number\(e\.unit_index\)\}`/);
  assert.match(source, /const baseline = state\.edits\[state\.selected\]\?\.evidence \|\| latestDraft\(state\.detail\)\?\.evidence/);
  assert.match(source, /state\.sources = \[\]; state\.sourceToken\+\+;/);
});

test('searchable source text remains available for exact quotation', () => {
  assert.match(source, /등록 원문 보기/);
  assert.match(source, /data-fill-quote/);
  assert.match(source, /if \(!quote\) return/);
  assert.match(source, /checkbox\.checked = true/);
  assert.match(source, /checkbox\.dispatchEvent\(new Event\("change", \{ bubbles: true \}\)\)/);
  assert.match(source, /original_evidence: \(res\.knowledge\?\.evidence \|\| \[\]\)\.slice\(0, 30\)/);
});

test('review module loads before the app on a cache-busted URL', () => {
  const reviews = html.search(/answer-reviews\.js\?v=/);
  const app = html.search(/[" ]src="app\.js\?v=/);
  assert.ok(reviews >= 0 && app >= 0 && reviews < app);
});

test('editor explains the exact question scope of an applied review', () => {
  assert.match(source, /같은 소속·자료 선택에서, 이 질문과 등록한 대체 질문에만 적용합니다/);
  assert.match(source, /다른 질문 전체를 자동으로 학습하지 않습니다/);
  assert.match(source, /적용 중지하고 다시 검토/);
});

test('comparison preserves the immutable original after applying that same version', () => {
  const { compareBaseline } = hooks();
  const original = { id: 'review-1', original_answer: '원래 답변', original_evidence: [{ source_id: 'source-1', quote: '원문' }] };
  const v1 = { id: 'v1', answer: '적용 답변', evidence: [{ source_id: 'source-1', quote: '수정 근거' }] };
  const afterApply = compareBaseline(original, v1, v1);
  assert.equal(afterApply.label, '최초 답변');
  assert.equal(afterApply.answer, '원래 답변');
  assert.equal(afterApply.evidence[0].quote, '원문');
  const nextDraft = compareBaseline(original, { id: 'v2', answer: '새 초안' }, v1);
  assert.equal(nextDraft.label, '현재 적용 답변');
  assert.equal(nextDraft.answer, '적용 답변');
});

test('selected item included outside the filter is identified in the list note', () => {
  assert.match(source, /현재 열어둔 항목 포함/);
  assert.match(source, /state\.selectedOutsideFilter = !!state\.selected && !state\.items\.some/);
});
