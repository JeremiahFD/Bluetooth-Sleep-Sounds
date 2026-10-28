import test from 'node:test';
import assert from 'node:assert/strict';
import {assignBinding,manualAssignment,bindingLabel,layoutPayload,vncDestination} from './remoteModel.js';

test('capture moves conflicting chord with source unchanged for Undo',()=>{
 const original={bindings:[{tokens:['k:304'],modified:false,action:'play_pause'},{tokens:['k:305'],modified:false,action:'next'}]};
 const result=assignBinding(original,1,{tokens:['k:304'],modified:false});
 assert.equal(result.moved,true);assert.equal(result.layout.bindings.length,1);assert.equal(result.layout.bindings[0].action,'next');
 assert.equal(original.bindings.length,2);assert.deepEqual(original.bindings[1].tokens,['k:305']);
});
test('normal and modified layers may reuse the same physical button',()=>{
 const original={bindings:[{tokens:['k:304'],modified:false,action:'play_pause'},{tokens:['k:305'],modified:true,action:'next'}]};
 const result=assignBinding(original,1,{tokens:['k:304'],modified:true});assert.equal(result.moved,false);assert.equal(result.layout.bindings.length,2);
});
test('capture appends a complete assignment without needing an empty saved row',()=>{
 const original={bindings:[{tokens:['k:304'],modified:false,action:'next'}],modifiers:[]};
 const result=assignBinding(original,1,{tokens:['k:310','k:305'],modified:false});
 assert.deepEqual(result.layout.bindings[1],{tokens:['k:305','k:310'],modified:false,action:'play_pause'});
 assert.equal(original.bindings.length,1);assert.equal(result.layout.bindings[0].action,'next');
});
test('an empty capture cannot append an incomplete assignment',()=>{
 const layout={bindings:[],modifiers:[]};
 assert.throws(()=>assignBinding(layout,0,{tokens:[],modified:false}),/Capture one to four/);
 assert.equal(layout.bindings.length,0);
});
test('manual additions preserve existing bindings and unrelated unsaved layout changes',()=>{
 const original={name:'Unsaved name',regular_delay:'1.5',modifiers:[],bindings:[{tokens:['k:304'],modified:false,action:'next'}]};
 const result=manualAssignment(original,1,{kind:'key',code:'305',modified:false});
 assert.equal(result.layout.name,'Unsaved name');assert.equal(result.layout.regular_delay,'1.5');assert.equal(result.layout.bindings.length,2);
 assert.equal(original.bindings.length,1);
});
test('manual validation rejects blank codes and missing modifiers instead of silently closing',()=>{
 const layout={modifiers:[],bindings:[]};
 assert.throws(()=>manualAssignment(layout,0,{kind:'key',code:'',modified:false}),/Enter a whole/);
 assert.throws(()=>manualAssignment(layout,0,{kind:'key',code:'304',modified:true}),/Assign a modifier/);
 assert.throws(()=>manualAssignment(layout,0,{kind:'axis',code:'767',direction:'+',modified:false}),/supported axis/);
 assert.equal(layout.bindings.length,0);
});
test('manual stick directions and conflicting assignments use the same move behavior',()=>{
 const layout={modifiers:['k:310'],bindings:[{tokens:['a:0:+'],modified:true,action:'next'}]};
 const result=manualAssignment(layout,1,{kind:'axis',code:'0',direction:'+',modified:true});
 assert.equal(result.moved,true);assert.equal(result.layout.bindings.length,1);assert.equal(layout.bindings[0].action,'next');
});
test('payload keeps exactly two delays and preserves bindings under any button',()=>{
 const value={name:'Bedtime',bindings:[{tokens:['k:304'],modified:false,action:'play_pause'}],modifiers:['k:310'],any_button:true,any_action:'play_default',regular_delay:'0.5',modified_delay:'1.2',dead_zone:'0.35'};
 const payload=layoutPayload(value);assert.equal(payload.regular_delay,.5);assert.equal(payload.modified_delay,1.2);assert.deepEqual(payload.bindings,value.bindings);assert.equal(payload.any_button,true);
});
test('labels show chords and stick direction',()=>{assert.match(bindingLabel({tokens:['k:310','a:0:+']}),/Left shoulder \+ Left stick horizontal positive/);});
test('VNC follows actual Pi server host with documented preview fallback',()=>{assert.deepEqual(vncDestination('192.0.2.133'),{address:'192.0.2.133:5900',url:'vnc://192.0.2.133:5900'});assert.equal(vncDestination('127.0.0.1').address,'127.0.0.1:5900');});
