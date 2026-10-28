import test from 'node:test';
import assert from 'node:assert/strict';
import {SleepSoundsApi} from './api.js';
import {readAudioSnapshot} from './audioRefresh.js';

const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
const reply=(data,status=200)=>({ok:status<400,status,json:async()=>data});

test('late pre-save volume status cannot replace an acknowledged volume, then fresh remote changes remain visible',async()=>{
 const old=deferred();let reads=0,volume=30,writes=0;
 const api=new SleepSoundsApi(async(path,options)=>{
  if(options?.method==='POST'){volume=JSON.parse(options.body).volume;writes++;return reply({ok:true});}
  if(++reads===1)return old.promise;
  return reply({csrf:'test',volume});
 });api.token='test';
 const delayed=readAudioSnapshot(api,()=>api.status());
 await api.settings({volume:80});
 old.resolve(reply({csrf:'test',volume:30}));
 assert.deepEqual(await delayed,{current:false,value:{csrf:'test',volume:30}});
 assert.equal((await readAudioSnapshot(api,()=>api.status())).value.volume,80);
 volume=45; // Another controller's subsequent edit is still authoritative.
 const later=await readAudioSnapshot(api,()=>api.status());
 assert.equal(later.current,true);assert.equal(later.value.volume,45);assert.equal(writes,1);
});

test('late effect config cannot rewind a successful toggle acknowledgement',async()=>{
 const old=deferred();
 const api=new SleepSoundsApi(async(path,options)=>options?.method==='POST'
  ?reply({audio_processing:{eq_enabled:true},audio_processing_revision:2})
  :old.promise);api.token='test';
 const delayed=readAudioSnapshot(api,()=>api.config());
 await api.audioProcessing({eq_enabled:true},1);
 old.resolve(reply({audio_processing:{eq_enabled:false},audio_processing_revision:1}));
 assert.equal((await delayed).current,false);
});

test('normalization mutation invalidates an in-flight multi-request refresh',async()=>{
 const old=deferred();const api=new SleepSoundsApi(async(path,options)=>options?.method==='POST'?reply({normalization:true}):old.promise);api.token='test';
 const delayed=readAudioSnapshot(api,()=>Promise.all([api.status(),api.config()]));
 await api.normalization(true);old.resolve(reply({csrf:'test',normalization:false}));
 assert.equal((await delayed).current,false);
});

test('failed writes and ordinary polling never create another control write',async()=>{
 let writes=0;
 const api=new SleepSoundsApi(async(path,options)=>{if(options?.method==='POST'){writes++;return reply({error:'busy'},409);}return reply({csrf:'test',volume:30});});api.token='test';
 const epoch=api.audioMutationEpoch;
 await assert.rejects(()=>api.settings({volume:80}),/busy/);
 assert.equal(api.audioMutationEpoch,epoch);
 for(let i=0;i<3;i++)assert.equal((await readAudioSnapshot(api,()=>api.status())).current,true);
 assert.equal(writes,1);
});
