import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mergeQueue,assignQueueImage} from './uploadQueue.js';
const f=n=>({name:n,size:100}),empty={jobs:[],images:[],seq:0},formats=['.mp3','.wav'];
test('multiple audio and cover images match by stem',()=>{
 const q=mergeQueue(empty,[f('Rain.mp3'),f('Ocean.wav'),f('Rain.jpg'),f('Ocean.png')],formats);
 assert.equal(q.jobs.length,2);
 for(const j of q.jobs)assert.ok(j.imageId);
});
test('two-file picker in either order',()=>{
 const q=mergeQueue(mergeQueue(empty,[f('picture.jpg')],formats),[f('sound.mp3')],formats);
 assert.equal(q.jobs[0].imageId,q.images[0].id);
});
test('ambiguous pictures require manual assignment',()=>{
 const q=mergeQueue(empty,[f('one.mp3'),f('two.mp3'),f('other.jpg')],formats);
 assert.equal(q.jobs[0].imageId,null);
 const chosen=assignQueueImage(q,q.jobs[1].id,q.images[0].id);
 assert.throws(()=>assignQueueImage(chosen,q.jobs[0].id,q.images[0].id),/already assigned/);
});
test('invalid file rejected',()=>assert.throws(()=>mergeQueue(empty,[f('bad.exe')],formats),/Unsupported/));
