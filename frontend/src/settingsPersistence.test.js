import {test} from 'node:test';
import assert from 'node:assert/strict';
import {settingsPayload,settingsPersisted} from './settingsPersistence.js';
const state={uploadGb:5,reserveMb:256,autoReconnect:true,reconnectMinutes:10,resumeAfterRestart:false};
test('settings payload excludes playback modes and timer',()=>{
 const p=settingsPayload(state);
 assert.equal(p.reconnect_retry_minutes,10);
 assert.equal(p.max_upload_bytes,5*1073741824);
 assert.ok(!('loop' in p));assert.ok(!('sleep_minutes' in p));
 assert.ok(settingsPersisted(p,p));
});
test('settings validate bounded parameters',()=>{
 for(const bad of [{uploadGb:0},{reserveMb:-1},{reconnectMinutes:1441}]){
  assert.throws(()=>settingsPayload({...state,...bad}));
 }
 assert.ok(!settingsPersisted({...settingsPayload(state),auto_reconnect:false},settingsPayload(state)));
});
