import {test} from 'node:test';
import assert from 'node:assert/strict';
import {rackOrder,moveEffect,effectEnabled} from './effectRack.js';
test('reordering changes the submitted list without losing effects or mutating base',()=>{
 const original=['gain','eq','compressor','limiter'];
 assert.deepEqual(moveEffect(original,'compressor','gain'),['compressor','gain','eq','limiter']);
 assert.deepEqual(original,['gain','eq','compressor','limiter']);
 assert.deepEqual(moveEffect(original,'unknown','gain'),original);
 assert.deepEqual(rackOrder(['echo','gain','echo','unknown']),['echo','gain']);
 assert.equal(effectEnabled('gain',{gain_enabled:false}),false);
 assert.equal(effectEnabled('compressor',{compressor_enabled:false}),false);
});
