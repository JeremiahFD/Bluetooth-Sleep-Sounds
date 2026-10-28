import test from 'node:test';
import assert from 'node:assert/strict';
import {assignBinding,bindingLabel,layoutPayload,vncDestination} from './remoteModel.js';

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
test('payload keeps exactly two delays and preserves bindings under any button',()=>{
 const value={name:'Bedtime',bindings:[{tokens:['k:304'],modified:false,action:'play_pause'}],modifiers:['k:310'],any_button:true,any_action:'play_default',regular_delay:'0.5',modified_delay:'1.2',dead_zone:'0.35'};
 const payload=layoutPayload(value);assert.equal(payload.regular_delay,.5);assert.equal(payload.modified_delay,1.2);assert.deepEqual(payload.bindings,value.bindings);assert.equal(payload.any_button,true);
});
test('labels show chords and stick direction',()=>{assert.match(bindingLabel({tokens:['k:310','a:0:+']}),/Left shoulder \+ Left stick horizontal positive/);});
test('VNC follows actual Pi server host with documented preview fallback',()=>{assert.deepEqual(vncDestination('192.0.2.133'),{address:'192.0.2.133:5900',url:'vnc://192.0.2.133:5900'});assert.equal(vncDestination('127.0.0.1').address,'127.0.0.1:5900');});
