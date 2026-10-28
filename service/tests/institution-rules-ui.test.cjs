const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(new URL('../static/institution-rules.js', `file://${__filename}`), 'utf8');

function harness(fetcher, search='') {
  const root = {
    dataset: {}, innerHTML: '', onclick: null, onchange: null, oninput: null, onsubmit: null,
    classList: {toggle() {}}, addEventListener() {}, querySelectorAll() { return []; },
    querySelector(selector) {
      if (selector === '[data-message]') return {hidden:true, textContent:'', classList:{toggle(){}}, setAttribute(){}};
      if (selector === '.ir-editor') return editor;
      if (selector === '.ir-categories') return categoryNav;
      if (selector === '.ir-list-items') return listItems;
      if (selector === '.ir-filter-note') return filterNote;
      return null;
    }
  };
  const editor = {innerHTML:''};
  const categoryNav = {innerHTML:''};
  const listItems = {innerHTML:'', insertAdjacentHTML(){}};
  const filterNote = {textContent:'', remove(){}};
  const window = {location:{search}};
  vm.runInNewContext(source, {
    document:{getElementById:()=>root}, window, fetch:fetcher,
    confirm:()=>true, location:{href:''}, URL, URLSearchParams, encodeURIComponent,
    console
  });
  return {root, editor, categoryNav, listItems, filterNote, module:window.SeomuInstitutionRules};
}

function response(data) { return {ok:true, json:async()=>data}; }

const detail = {id:'rule-1', revision:3, title:'검토 규정', category:'예산·회계', kind:'기관 규정', institution:'가람시', keywords:['검토'], active_version_id:'v1', enabled:true, versions:[
  {id:'v1', number:1, text:'이전 본문', title:'검토 규정', kind:'기관 규정', institution:'가람시', keywords:['검토']},
  {id:'v2', number:2, text:'최신 초안 본문', title:'검토 규정', kind:'기관 규정', institution:'가람시', keywords:['검토']}
], events:[]};

test('public_read_only false stays editable while true disables mutations', async () => {
  for (const readOnly of [false, true]) {
    const ui = harness(async () => response({items:[], public_read_only:readOnly}));
    await ui.module.load();
    const newButton = ui.root.innerHTML.match(/<button[^>]*data-action="new"[^>]*>/)?.[0] || '';
    assert.equal(newButton.includes('disabled'), readOnly);
  }
});

test('selecting a rule opens the newest version even when an older version is active', async () => {
  const ui = harness(async url => String(url).endsWith('/rule-1') ? response(detail) : response({items:[{id:'rule-1',title:'검토 규정',enabled:true,active_version_id:'v1'}],public_read_only:false}));
  await ui.module.load();
  await ui.root.onclick({target:{closest(selector){return selector==='[data-select]'?{dataset:{select:'rule-1'}}:null;}}});
  assert.match(ui.editor.innerHTML, /value="v2" selected/);
  assert.match(ui.editor.innerHTML, /최신 초안 본문/);
});

test('URL rule and cited version select the matching version, falling back to newest when missing', async () => {
  for (const [search,expectedVersion,expectedText] of [
    ['?rule=rule-1&rule_version=v1','v1','이전 본문'],
    ['?rule=rule-1&rule_version=missing','v2','최신 초안 본문']
  ]) {
    const calls=[];
    const ui=harness(async url=>{calls.push(String(url));return String(url).endsWith('/rule-1')?response(detail):response({items:[{id:'rule-1',title:'검토 규정',enabled:true,active_version_id:'v1'}],public_read_only:false});},search);
    await ui.module.load();
    assert.ok(calls.includes('/api/institution-rules/rule-1'));
    assert.match(ui.editor.innerHTML,new RegExp(`value="${expectedVersion}" selected`));
    assert.match(ui.editor.innerHTML,new RegExp(expectedText));
  }
});

test('chat is disabled with an explanation when the rule has no active version', async () => {
  const inactive = {...detail, enabled:false, active_version_id:null};
  const ui = harness(async url => String(url).endsWith('/rule-1') ? response(inactive) : response({items:[{id:'rule-1',title:'검토 규정',enabled:false}],public_read_only:false}));
  await ui.module.load();
  await ui.root.onclick({target:{closest(selector){return selector==='[data-select]'?{dataset:{select:'rule-1'}}:null;}}});
  const chatButton = ui.editor.innerHTML.match(/<button[^>]*data-action="chat"[^>]*>/)?.[0] || '';
  assert.match(chatButton, /disabled/);
  assert.match(ui.editor.innerHTML, /적용된 자료만 질문에 사용할 수 있습니다\./);
});

test('inactive rule labels its retained active version as the last applied version', async () => {
  const inactive = {...detail, enabled:false};
  const ui = harness(async url => String(url).endsWith('/rule-1') ? response(inactive) : response({items:[{id:'rule-1',title:'검토 규정',enabled:false,active_version_id:'v1'}],public_read_only:false}));
  await ui.module.load();
  await ui.root.onclick({target:{closest(selector){return selector==='[data-select]'?{dataset:{select:'rule-1'}}:null;}}});
  assert.match(ui.editor.innerHTML, /v1 · 마지막 적용본/);
  assert.doesNotMatch(ui.editor.innerHTML, /v1 · 적용 중/);
});

test('list refresh preserves the current version and balances an overlapping stale request', async () => {
  let resolveFirst;
  let requests=0;
  const ui=harness(async () => {
    requests++;
    if(requests===1) return new Promise(resolve=>{resolveFirst=()=>resolve(response({items:[],public_read_only:false,notice:'stale'}));});
    return response({items:[],public_read_only:false,notice:'current'});
  });
  const first=ui.module.load();
  await ui.module.load();
  assert.match(ui.root.innerHTML,/current/);
  resolveFirst(); await first;
  assert.match(ui.root.innerHTML,/current/);
  assert.doesNotMatch(ui.root.innerHTML,/stale/);
});


test('category filters count visible records and retain the active editor and dirty edits', async () => {
  const items=[
    {id:'rule-1',title:'검토 규정',category:'예산·회계',enabled:true},
    {id:'legacy',title:'오래된 자료',enabled:false},
    {id:'deleted',title:'삭제 자료',category:'기타',deleted:true}
  ];
  const ui=harness(async url=>String(url).endsWith('/rule-1')?response(detail):response({items,categories:['미분류','예산·회계','복무·휴가','출장·여비','물품·계약','교육·행사','문서·기록','보안·개인정보','기타'],public_read_only:false}));
  await ui.module.load();
  await ui.root.onclick({target:{closest(selector){return selector==='[data-select]'?{dataset:{select:'rule-1'}}:null;}}});
  ui.root.oninput({target:{closest:()=>({})}});
  const before=ui.editor.innerHTML;
  await ui.root.onclick({target:{closest(selector){return selector==='[data-category]'?{dataset:{category:'미분류'}}:null;}}});
  assert.equal(ui.editor.innerHTML,before);
  assert.match(ui.categoryNav.innerHTML,/data-category="미분류" aria-pressed="true">미분류 <span>1<\/span>/);
  assert.match(ui.filterNote.textContent,/현재 편집 중인 자료는 이 분류에 포함되지 않습니다\. 편집 내용은 유지됩니다\./);
  assert.doesNotMatch(ui.listItems.innerHTML,/data-select="deleted"/);
});

test('legacy category defaults to 미분류 and selected category seeds a new form', async () => {
  const ui=harness(async()=>response({items:[{id:'legacy',title:'오래된 자료'}],public_read_only:false}));
  await ui.module.load();
  assert.match(ui.root.innerHTML,/data-category="미분류"[^>]*>미분류 <span>1<\/span>/);
  await ui.root.onclick({target:{closest(selector){return selector==='[data-category]'?{dataset:{category:'복무·휴가'}}:null;}}});
  await ui.root.onclick({target:{closest(selector){return selector==='[data-action]'?{dataset:{action:'new'}}:null;}}});
  assert.match(ui.editor.innerHTML,/<option value="복무·휴가" selected>복무·휴가<\/option>/);
});
