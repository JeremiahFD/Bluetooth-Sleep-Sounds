import test from 'node:test';
import assert from 'node:assert/strict';
import {SleepSoundsApi} from './api.js';
import {fromConfig,payloadFor} from './settingsModel.js';

test('rating and comment writes keep the initiating profile during token lookup',async()=>{
 for(const method of ['rating','postTrackComment']){
  let unlock;const gate=new Promise(resolve=>unlock=resolve);let body;
  const api=new SleepSoundsApi(async(path,options)=>{if(path==='/api/status')await gate;else body=JSON.parse(options.body);return {ok:true,status:200,json:async()=>({csrf:'token',posts:[]})}});
  api.setProfileId('first');const pending=method==='rating'?api.rating('Rain.wav',4):api.postTrackComment('Rain.wav','Nice rain');
  api.setProfileId('second');unlock();await pending;assert.equal(body.profile,'first');
 }
});
test('deletion sends exact confirmation and comments encode only their track scope',async()=>{
 const calls=[];const api=new SleepSoundsApi(async(path,options)=>{calls.push([path,options?.body&&JSON.parse(options.body)]);return {ok:true,status:200,json:async()=>({posts:[]})}});api.token='token';
 await api.deleteTrack('Rain & thunder.wav');await api.trackComments('Rain & thunder.wav');await api.postTrackComment('Rain & thunder.wav','Reply','parent');
 assert.deepEqual(calls[0],['/api/track-delete',{track:'Rain & thunder.wav',confirm:true}]);
 assert.equal(calls[1][0],'/api/track-comments?track=Rain%20%26%20thunder.wav');
 assert.deepEqual(calls[2][1],{track:'Rain & thunder.wav',body:'Reply',parent:'parent',profile:'none'});
});
test('deletion is opt-in and keeps a boolean through settings autosave',()=>{
 assert.equal(fromConfig({}).allow_track_deletion,false);
 assert.equal(fromConfig({allow_track_deletion:true}).allow_track_deletion,true);
 assert.deepEqual(payloadFor({allow_track_deletion:false},['allow_track_deletion']),{allow_track_deletion:false});
});
