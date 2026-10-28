import test from 'node:test';
import assert from 'node:assert/strict';
import {needsAudioConfigRefresh} from './audioRefresh.js';
test('other-client DSP revisions refresh config without a full library request',()=>{
 assert.equal(needsAudioConfigRefresh({audio_processing_revision:3,volume:30},{audio_processing_revision:2,volume:30}),true);
 assert.equal(needsAudioConfigRefresh({audio_processing_revision:3,volume:30},{audio_processing_revision:3,volume:30}),false);
 assert.equal(needsAudioConfigRefresh({audio_processing_revision:2,volume:30},{audio_processing_revision:3,volume:30}),false);
});
test('live volume refreshes config while missing older-server fields do not loop',()=>{
 assert.equal(needsAudioConfigRefresh({volume:32},{volume:30,audio_processing_revision:1}),true);
 assert.equal(needsAudioConfigRefresh({},{volume:30,audio_processing_revision:1}),false);
 assert.equal(needsAudioConfigRefresh({},null),true);
});
