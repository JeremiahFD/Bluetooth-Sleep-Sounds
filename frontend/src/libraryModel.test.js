import test from 'node:test';
import assert from 'node:assert/strict';
import {matchesSearch,filterLibrary,usedTags,DEFAULT_FILTERS,searchTerms} from './libraryModel.js';
const rain={id:'rain.flac',name:'Rain on the roof',metadata:{description:'Quiet water, no storm',tags:['rain','roof'],categories:['weather'],added_at:20},my_rating:5,rating:4,duration_seconds:100,codec:'flac',sample_rate_hz:44100,bit_depth_bits:16,last_played_at:30,ratings:[{profile:'other',rating:1}]};
const train={id:'train.mp3',name:'Train at Night',metadata:{description:'Thunder outside',tags:['travel'],categories:['travel'],added_at:10},my_rating:1,rating:5,duration_seconds:20,codec:'mp3',sample_rate_hz:44100,bitrate_kbps:320,ratings:[{profile:'other',rating:5}]};
const unknown={id:'unknown.wav',name:'Unknown',metadata:{}};
const f=changes=>({...DEFAULT_FILTERS,...changes});
test('quoted, excluded and Unicode searches are safe and word-aware',()=>{
 assert.equal(matchesSearch(rain,'"rain on" -thunder'),true);
 assert.equal(matchesSearch(train,'-rain'),true);
 assert.equal(matchesSearch(train,'-"at night"'),false);
 assert.equal(matchesSearch(train,'thunder'),false);
 assert.equal(matchesSearch(train,'thunder',true),true);
 assert.equal(matchesSearch(train,'-thunder',true),false);
 assert.equal(matchesSearch(rain,'"rain on'),true);
 assert.deepEqual(searchTerms('-'),[{value:'-',exclude:false}]);
 assert.equal(matchesSearch({name:'Été pluie'},'été'),true);
 assert.equal(matchesSearch(rain,'[a-z]+'),false);
});
test('include all, exclude any, category and text intersect without changing source',()=>{
 const rows=[rain,train];assert.deepEqual(filterLibrary(rows,f({include:['rain','roof'],exclude:['travel'],category:'weather',query:'roof'})).map(t=>t.id),['rain.flac']);
 assert.equal(filterLibrary(rows,f({include:['rain','travel']})).length,0);
 assert.equal(filterLibrary(rows,f({include:['rain'],exclude:['rain']})).length,0);
 assert.equal(rows[0],rain);
});
test('rating sorts are real and missing values remain last in both directions',()=>{
 for(const descending of [true,false]){
  const rating=filterLibrary([unknown,rain,train],f({sort:'rating',descending}));
  assert.equal(rating.at(-1),unknown);assert.equal(rating[0],descending?train:rain);
  assert.equal(filterLibrary([unknown,rain,train],f({sort:'mine',descending}))[0],descending?rain:train);
 }
 assert.equal(filterLibrary([rain,train],f({sort:'mine',ratingProfile:'other',descending:true}))[0],train);
});
test('technical quality, date, recently played and length preserve unknown-last',()=>{
 assert.equal(filterLibrary([train,rain],f({sort:'quality'}))[0],rain);
 assert.equal(filterLibrary([train,rain],f({sort:'added'}))[0],rain);
 assert.equal(filterLibrary([train,rain],f({sort:'recent'}))[0],rain);
 assert.equal(filterLibrary([train,rain],f({sort:'length',descending:false}))[0],train);
});
test('only assigned tags appear in search filter picker',()=>{
 assert.deepEqual(usedTags([rain],{tags:[{id:'rain'},{id:'unused'},{id:'roof'}]}).map(t=>t.id),['rain','roof']);
});
