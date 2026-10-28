import {test} from 'node:test';
import assert from 'node:assert/strict';
import {SleepSoundsApi} from './api.js';
test('controls obtain token and use same-origin API', async () => {
  const calls = [];
  const api = new SleepSoundsApi(async (path, options) => {
    calls.push([path, options]);
    return {ok:true, json:async () => path === '/api/status' ? {csrf:'test-token'} : {ok:true}};
  });
  await api.sleep('Rain.wav', 60);
  assert.equal(calls[0][0], '/api/status');
  assert.equal(calls[1][1].headers['X-Sleep-Token'], 'test-token');
  assert.deepEqual(JSON.parse(calls[1][1].body), {track:'Rain.wav', minutes:60, profile:'none'});
});
test('server errors remain actionable', async () => {
  const api = new SleepSoundsApi(async () => ({ok:false, json:async () => ({error:'Output disconnected'})}));
  await assert.rejects(api.status(), /Output disconnected/);
});

test('deleted remembered profile falls back to None for the library', async () => {
  const calls=[];
  const api=new SleepSoundsApi(async path=>{calls.push(path);
    if(path.includes('profile=deleted'))return {ok:false,status:400,json:async()=>({error:'That profile is no longer available. Choose another profile.'})};
    return {ok:true,status:200,json:async()=>[]};
  });
  api.setProfileId('deleted');
  assert.deepEqual(await api.tracks(),[]);
  assert.equal(api.profileId,'none');
  assert.deepEqual(calls,['/api/tracks?profile=deleted','/api/tracks?profile=none']);
});

test('uploadWithProgress sends audio bytes with same-origin request token', async () => {
  const previous = globalThis.XMLHttpRequest;
  const calls = [];
  class MockXHR {
    constructor() {this.headers = {};this.upload = {};this.status=201;this.responseText='{"id":"Rain.wav"}';}
    open(method,path) {this.method=method;this.path=path;}
    setRequestHeader(k,v) {this.headers[k]=v;}
    send(file) {
      calls.push({file,method:this.method,path:this.path,headers:this.headers});
      this.upload.onprogress?.({lengthComputable:true,loaded:50,total:100});
      this.onload();
    }
    abort() { this.onabort?.(); }
  }
  globalThis.XMLHttpRequest=MockXHR;
  try {
    const api = new SleepSoundsApi(async path => ({ok:true,status:200,json:async()=>({csrf:'upload-token'})}));
    const progress=[];
    const file={name:'Rain.wav',size:100};
    const job=api.uploadWithProgress(file,p=>progress.push(p));
    const result=await job.promise;
    assert.deepEqual(result,{id:'Rain.wav'});
    assert.deepEqual(progress,[50]);
    assert.equal(calls[0].path,'/api/upload?name=Rain.wav');
    assert.equal(calls[0].headers['X-Sleep-Token'],'upload-token');
    assert.equal(calls[0].file,file);
  } finally {globalThis.XMLHttpRequest=previous;}
});
test('thumbnail upload targets the exact saved audio id', async()=>{
  const previous=globalThis.XMLHttpRequest;
  const calls=[];
  class MockXHR {
    constructor(){this.upload={};this.status=201;this.responseText='{"artwork":"/api/artwork?track=Rain.mp3"}';}
    open(method,path){calls.push({method,path});}
    setRequestHeader(){}
    send(){this.onload();}
    abort(){}
  }
  globalThis.XMLHttpRequest=MockXHR;
  try{
    const api=new SleepSoundsApi(async()=>({ok:true,status:200,json:async()=>({csrf:'token'})}));
    const task=api.uploadThumbnailWithProgress('Rain (ad14).mp3',{name:'Moonlight.jpg',size:1200});
    await task.promise;
    assert.equal(calls[0].path,'/api/artwork?track=Rain%20(ad14).mp3&name=Moonlight.jpg');
  }finally{globalThis.XMLHttpRequest=previous;}
});

test('selectTrack sends current profile and invalidates older audio snapshots',async()=>{
 const requests=[];
 const api=new SleepSoundsApi(async (path,opts)=>{
  requests.push({path,opts});
  return {ok:true,status:200,json:async()=>path==='/api/status'?{csrf:'token'}:{ok:true}};
 });
 api.setProfileId('listener');
 await api.selectTrack('Rain.wav');
 assert.equal(requests[1].path,'/api/select-track');
 assert.deepEqual(JSON.parse(requests[1].opts.body),{track:'Rain.wav',profile:'listener'});
 assert.equal(api.audioMutationEpoch,1);
});
