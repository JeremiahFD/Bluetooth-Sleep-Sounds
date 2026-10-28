import {test} from 'node:test';
import assert from 'node:assert/strict';
import {SleepSoundsApi} from './api.js';
test('favorites and normalization send explicit idempotent values',async()=>{
 const requests=[];const api=new SleepSoundsApi(async(path,options)=>{requests.push([path,options?.body&&JSON.parse(options.body)]);return {ok:true,status:200,json:async()=>path==='/api/status'?{csrf:'token'}:{ok:true}}});
 await api.favorite('Rain.wav',true);await api.normalization(false);await api.pause(true);
 assert.ok(requests.some(([p,b])=>p==='/api/favorite'&&b.favorite===true&&b.track==='Rain.wav'));
 assert.ok(requests.some(([p,b])=>p==='/api/normalization'&&b.enabled===false));
 assert.ok(requests.some(([p,b])=>p==='/api/pause'&&b.paused===true));
});
test('completed upload receipt avoids retransmitting audio',async()=>{
 const old=globalThis.XMLHttpRequest;let sends=0;
 class XHR{constructor(){this.upload={}}abort(){}send(){sends++}}
 globalThis.XMLHttpRequest=XHR;
 try{const api=new SleepSoundsApi(async(path)=>({ok:true,status:200,json:async()=>path==='/api/status'?{csrf:'token'}:{complete:true,id:'Rain.wav'}}));
 const result=await api.uploadWithProgress({name:'Rain.wav',size:10},()=>{},'a'.repeat(32)).promise;
 assert.equal(result.id,'Rain.wav');assert.equal(result.reused,true);assert.equal(sends,0);
 }finally{globalThis.XMLHttpRequest=old}
});
test('cancel before token lookup never starts upload',async()=>{
 const old=globalThis.XMLHttpRequest;let sends=0;class XHR{constructor(){this.upload={}}abort(){}send(){sends++}};globalThis.XMLHttpRequest=XHR;
 try{const api=new SleepSoundsApi(async()=>({ok:true,status:200,json:async()=>({csrf:'token'})}));const job=api.uploadWithProgress({name:'Rain.wav'});job.abort();await assert.rejects(job.promise,/cancelled/);assert.equal(sends,0);}finally{globalThis.XMLHttpRequest=old}
});
