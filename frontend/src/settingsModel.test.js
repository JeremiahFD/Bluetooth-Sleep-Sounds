import test from 'node:test';
import assert from 'node:assert/strict';
import {fromConfig,payloadFor} from './settingsModel.js';
test('playback buffer milliseconds round trip to host seconds',()=>{
 assert.equal(fromConfig({audio_buffer_seconds:0.85}).audio_buffer_ms,850);
 assert.equal(fromConfig({}).audio_buffer_ms,500);
 assert.deepEqual(payloadFor({audio_buffer_ms:'850'},['audio_buffer_ms']),{audio_buffer_seconds:0.85});
 assert.deepEqual(payloadFor({audio_buffer_ms:100},['audio_buffer_ms']),{audio_buffer_seconds:0.1});
 assert.deepEqual(payloadFor({audio_buffer_ms:2000},['audio_buffer_ms']),{audio_buffer_seconds:2});
});
test('invalid buffer edits cannot enter autosave payload',()=>{
 for(const value of ['',null,true,false,NaN,Infinity,-Infinity,99,2001,'bad']){
  assert.throws(()=>payloadFor({audio_buffer_ms:value},['audio_buffer_ms']));
 }
});
