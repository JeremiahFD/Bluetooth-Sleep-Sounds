import {test} from 'node:test';
import assert from 'node:assert/strict';
import {browsingPreferences,miniPlayerTrack,shouldShowMiniPlayer} from './browsingPreferences.js';

test('new and None profiles default to Library with bottom mini-player',()=>{
 const p=browsingPreferences({});
 assert.equal(p.openNowPlayingOnSelect,false);
 assert.equal(p.showMiniPlayer,true);
});
test('per-profile navigation never inherits another profile choice',()=>{
 const kristina={open_now_playing_on_select:true,show_mini_player:false};
 const none={open_now_playing_on_select:false,show_mini_player:true};
 assert.equal(browsingPreferences(kristina).openNowPlayingOnSelect,true);
 assert.equal(browsingPreferences(none).openNowPlayingOnSelect,false);
 assert.equal(browsingPreferences(none).showMiniPlayer,true);
});
test('only exact boolean true enables automatic navigation and false hides bar',()=>{
 assert.deepEqual(browsingPreferences({open_now_playing_on_select:'true',show_mini_player:null}),
   {openNowPlayingOnSelect:false,showMiniPlayer:true});
 assert.deepEqual(browsingPreferences({show_mini_player:false}),
   {openNowPlayingOnSelect:false,showMiniPlayer:false});
});
test('mini-player shows paused or playing recording and an idle selection',()=>{
 const tracks=[{id:'rain.wav'},{id:'thunder.wav'}];
 const paused={idle:false,paused:true,selected:'rain.wav'};
 const playing={...paused,paused:false};
 const idle={idle:true,selected:'thunder.wav'};
 assert.equal(miniPlayerTrack(paused,tracks,'thunder.wav').id,'rain.wav');
 assert.equal(miniPlayerTrack(playing,tracks,'rain.wav').id,'rain.wav');
 assert.equal(miniPlayerTrack(idle,tracks,'rain.wav').id,'thunder.wav');
 assert.equal(shouldShowMiniPlayer('library',idle,tracks[1],{}),true);
 assert.equal(shouldShowMiniPlayer('library',paused,tracks[0],{show_mini_player:false}),false);
 assert.equal(shouldShowMiniPlayer('home',paused,tracks[0],{}),false);
});
