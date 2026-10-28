import {test} from 'node:test';
import assert from 'node:assert/strict';
import {classifyMediaFiles} from './mediaSelection.js';
const ext=['.mp3','.flac','.wav'];
const file=name=>({name,size:1024});
test('shift-selected audio and image work in either order',()=>{
 for(const selected of [[file('night.png'),file('Rain.mp3')],[file('Rain.mp3'),file('night.png')]]){
  const result=classifyMediaFiles(selected,ext);
  assert.equal(result.audio.name,'Rain.mp3');
  assert.equal(result.image.name,'night.png');
 }
});
test('single chosen audio/image and correction of invalid group',()=>{
 assert.equal(classifyMediaFiles([file('x.webp')],ext).audio,null);
 assert.equal(classifyMediaFiles([file('x.flac')],ext).image,null);
 assert.throws(()=>classifyMediaFiles([file('a.mp3'),file('b.wav')],ext),/at most one audio/);
 assert.throws(()=>classifyMediaFiles([file('image.svg')],ext),/Unsupported/);
});
