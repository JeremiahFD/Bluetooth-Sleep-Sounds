import test from 'node:test';
import assert from 'node:assert/strict';
import {LiveAudioEditor} from './liveAudioEditor.js';
import {SleepSoundsApi} from './api.js';
const initial=()=>({audio_processing:{gain_db:0,eq_enabled:false,eq_mid_db:0,bypass:false},normalization:false,audio_processing_revision:0});
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};

test('cold page startup accepts null config and adopts the first server snapshot',()=>{
 const editor=new LiveAudioEditor({config:null,save:async()=>initial()});
 assert.equal(editor.snapshot().dirty,false);
 editor.receive(initial());
 assert.equal(editor.snapshot().draft.gain_db,0);
 editor.dispose();
});

test('edits during an in-flight update remain editable, serialize, and settle saved',async()=>{
 let server=initial(),calls=[],active=0,maxActive=0;const first=deferred();
 const editor=new LiveAudioEditor({config:server,delay:60000,save:async patch=>{calls.push(patch);maxActive=Math.max(maxActive,++active);if(calls.length===1)await first.promise;server={...server,audio_processing:{...server.audio_processing,...patch},audio_processing_revision:server.audio_processing_revision+1};active--;return server;}});
 editor.edit({gain_db:1});const saving=editor.flush();
 editor.edit({gain_db:3});editor.edit({eq_enabled:true});
 assert.equal(editor.snapshot().draft.gain_db,3);assert.equal(editor.snapshot().saving,true);
 first.resolve();await saving;
 assert.equal(maxActive,1);assert.deepEqual(calls,[{gain_db:1},{gain_db:3,eq_enabled:true}]);
 assert.equal(editor.snapshot().dirty,false);assert.equal(editor.snapshot().saved,true);assert.equal(editor.snapshot().draft.gain_db,3);editor.dispose();
});

test('authoritative acknowledgement clears pending without a racy second GET comparison',async()=>{
 const config=initial();let editor;editor=new LiveAudioEditor({config,delay:60000,save:async patch=>({...config,audio_processing:{...config.audio_processing,...patch},audio_processing_revision:2})});
 editor.edit({eq_enabled:true});await editor.flush();
 editor.receive({...config,audio_processing_revision:1});
 assert.equal(editor.snapshot().draft.eq_enabled,true);assert.equal(editor.snapshot().dirty,false);editor.dispose();
});

test('other-client fields update while local field intent is retained',async()=>{
 let server=initial();const editor=new LiveAudioEditor({config:server,delay:60000,save:async patch=>({...server,audio_processing:{...server.audio_processing,...patch},audio_processing_revision:3})});
 editor.edit({gain_db:2});server={...server,audio_processing:{...server.audio_processing,eq_mid_db:-4},audio_processing_revision:2};editor.receive(server);
 assert.equal(editor.snapshot().draft.eq_mid_db,-4);assert.equal(editor.snapshot().draft.gain_db,2);await editor.flush();assert.equal(editor.snapshot().draft.eq_mid_db,-4);editor.dispose();
});

test('failed updates retain exact desired settings for explicit retry',async()=>{
 const config=initial();let fail=true;const editor=new LiveAudioEditor({config,delay:60000,save:async patch=>{if(fail)throw Error('Editing is locked');return {...config,audio_processing:{...config.audio_processing,...patch},audio_processing_revision:1};}});
 editor.edit({eq_enabled:true});assert.equal(await editor.flush(),false);assert.equal(editor.snapshot().dirty,true);assert.match(editor.snapshot().error,/locked/);
 fail=false;assert.equal(await editor.flush(),true);assert.equal(editor.snapshot().dirty,false);editor.dispose();
});

test('leaving a page flushes pending values instead of cancelling the last adjustment',async()=>{
 const config=initial(),done=deferred();let patch;const editor=new LiveAudioEditor({config,delay:60000,save:async value=>{patch=value;done.resolve();return {...config,audio_processing:{...config.audio_processing,...value},audio_processing_revision:1};}});
 editor.edit({eq_enabled:true});editor.dispose();await done.promise;assert.deepEqual(patch,{eq_enabled:true});
});

test('audio API serializes volume, sparse effect and normalization edits with one session',async()=>{
 const calls=[],first=deferred();let active=0,max=0;
 const api=new SleepSoundsApi(async(path,options)=>{max=Math.max(max,++active);calls.push([path,JSON.parse(options.body)]);if(calls.length===1)await first.promise;active--;return {ok:true,status:200,json:async()=>({...initial(),audio_processing_revision:calls.length})};});api.token='test';
 const volume=api.settings({volume:30}),effects=api.saveLiveAudio({eq_enabled:true}),normal=api.normalization(true);await Promise.resolve();first.resolve();await Promise.all([volume,effects,normal]);
 assert.equal(max,1);assert.deepEqual(calls.map(([path])=>path),['/api/settings','/api/audio-processing','/api/normalization']);assert.deepEqual(calls[1][1].settings,{eq_enabled:true});assert.ok(calls.every(([,body])=>body.editor_session===api.editorSession));assert.equal(calls[1][1].expected_revision,undefined);
});

test('two independent profile clients send sparse patches and retain both users changes',async()=>{
 let server=initial();const fetcher=async(path,options)=>{const body=JSON.parse(options.body);server={...server,audio_processing:{...server.audio_processing,...body.settings},audio_processing_revision:server.audio_processing_revision+1};return {ok:true,status:200,json:async()=>server};};
 const a=new SleepSoundsApi(fetcher),b=new SleepSoundsApi(fetcher);a.token=b.token='test';a.setProfileId('jeremiah');b.setProfileId('fake-test');
 await a.saveLiveAudio({gain_db:-2});await b.saveLiveAudio({eq_enabled:true});assert.equal(server.audio_processing.gain_db,-2);assert.equal(server.audio_processing.eq_enabled,true);assert.notEqual(a.editorSession,b.editorSession);
});
