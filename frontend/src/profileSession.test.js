import {test} from 'node:test';
import assert from 'node:assert/strict';
import {shouldPromptForProfile,rememberProfileEnabled} from './profileSession.js';
test('remembered valid profile skips new-session prompt; missing/deleted profiles require choice',()=>{
 const state={enabled:true,valid:true,remember:true,saved:'none',confirmed:false};
 assert.equal(shouldPromptForProfile(state),false);
 assert.equal(shouldPromptForProfile({...state,saved:null}),true);
 assert.equal(shouldPromptForProfile({...state,valid:false,confirmed:true}),true);
 assert.equal(shouldPromptForProfile({...state,enabled:false}),false);
 assert.equal(shouldPromptForProfile({...state,remember:false}),true);
 assert.equal(shouldPromptForProfile({...state,remember:false,confirmed:true}),false);
 assert.equal(rememberProfileEnabled({getItem:()=>null}),true);
});
