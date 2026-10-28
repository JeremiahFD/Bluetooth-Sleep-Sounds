import test from 'node:test';
import assert from 'node:assert/strict';
import {THEMES,resolveTheme,nativeOwnsInsets} from './themes.js';
import {SleepSoundsApi} from './api.js';

test('existing themes plus Cloudstorm are available with unique IDs',()=>{
 assert.deepEqual(THEMES.map(t=>t.id),['moonlit','forest','deck','cloudstorm']);
 assert.equal(new Set(THEMES.map(t=>t.id)).size,THEMES.length);
});
test('Cloudstorm uses only the local supplied photograph',()=>{
 assert.equal(resolveTheme('cloudstorm').artwork,'/ui/cloudstorm/cloudstorm-original.jpg');
});
test('unknown saved appearance has a safe fallback',()=>{
 for(const id of [null,'','bad','https://external.test/image'])assert.equal(resolveTheme(id).id,'moonlit');
});
test('native inset ownership uses an explicit shell marker, not all Android browsers',()=>{
 assert.equal(nativeOwnsInsets('Mozilla/5.0 Android SleepSoundsAndroid/0.3'),true);
 for(const ua of ['',null,'Mozilla/5.0 Android Chrome/120.0','NotSleepSoundsAndroid/1'])assert.equal(nativeOwnsInsets(ua),false);
});
test('audio processing API sends typed settings and expected revision',async()=>{
 let request;
 const api=new SleepSoundsApi(async(path,options)=>{request={path,options};return {ok:true,status:200,json:async()=>({revision:2,settings:{gain_db:3}})}});
 api.token='test';const result=await api.audioProcessing({gain_db:3},1);
 assert.equal(request.path,'/api/audio-processing');assert.deepEqual(JSON.parse(request.options.body),{settings:{gain_db:3},expected_revision:1,profile:'none',editor_session:api.editorSession});
 assert.equal(result.revision,2);
});
