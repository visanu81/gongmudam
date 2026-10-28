import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source=readFileSync(new URL('../desktop/embedded.js',import.meta.url),'utf8');
function setup(){
  const listeners=new Map(),calls=[],parent={postMessage(){}};
  const banner={setAttribute(){},textContent:''};
  const window={parent,addEventListener:(type,fn)=>listeners.set(type,fn),fetch:async(input,init)=>{calls.push({input,body:JSON.parse(init.body)});return {ok:true};}};
  const document={readyState:'loading',addEventListener(){},getElementById:()=>banner};
  vm.runInNewContext(source,{window,document,location:{origin:'http://127.0.0.1:8787',href:'http://127.0.0.1:8787/index.html'},URL,Request,clearTimeout,Date});
  const context=(profile,origin='http://127.0.0.1:8787',sender=parent)=>listeners.get('message')({origin,source:sender,data:{type:'gongmudam:context',profile}});
  const ask=()=>window.fetch('/api/ask',{method:'POST',body:JSON.stringify({query:'교육에 참여하려는데 언제까지 내나요?',guidance:true,use_ai:false})});
  return {calls,context,ask};
}
const first={confirmed:true,personnel_framework:'national_public_official',organization:'검증기관 A',region:'서울',department:'총무과'};
test('confirmed affiliation is a separate field, never appended to the user question',async()=>{
  const ui=setup();ui.context(first);await ui.ask();
  assert.equal(ui.calls[0].body.query,'교육에 참여하려는데 언제까지 내나요?');
  assert.equal(ui.calls[0].body.affiliation.organization,'검증기관 A');
  assert.equal(ui.calls[0].body.affiliation.confirmed,true);
  assert.equal(ui.calls[0].body.use_ai,false);
});
test('changing and clearing affiliation takes effect on the next request without leakage',async()=>{
  const ui=setup();ui.context(first);await ui.ask();
  ui.context({...first,organization:'검증기관 B'});await ui.ask();
  ui.context(null);await ui.ask();
  assert.equal(ui.calls[1].body.affiliation.organization,'검증기관 B');
  assert.equal(ui.calls[2].body.affiliation,undefined);
});
test('unconfirmed or untrusted context cannot set affiliation',async()=>{
  for(const [profile,origin,sender] of [[{...first,confirmed:false},undefined,undefined],[first,'https://evil.test',undefined],[first,undefined,{}]]){
    const ui=setup();ui.context(profile,origin,sender);await ui.ask();
    assert.equal(ui.calls[0].body.affiliation,undefined);
  }
});
