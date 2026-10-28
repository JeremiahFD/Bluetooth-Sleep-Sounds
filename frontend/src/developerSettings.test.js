import test from 'node:test';
import assert from 'node:assert/strict';
import {GAIN_METER_KEY,readGainMeterEnabled,saveGainMeterEnabled} from './developerSettings.js';

test('live meter starts off and stays off unless explicitly enabled',()=>{
 const values=new Map();
 const storage={getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,value)};
 assert.equal(readGainMeterEnabled(storage),false);
 assert.equal(saveGainMeterEnabled(true,storage),true);
 assert.equal(values.get(GAIN_METER_KEY),'true');
 assert.equal(readGainMeterEnabled(storage),true);
 assert.equal(saveGainMeterEnabled(false,storage),false);
 assert.equal(readGainMeterEnabled(storage),false);
});

test('blocked storage falls back to meter off',()=>{
 const storage={getItem:()=>{throw Error('blocked')},setItem:()=>{throw Error('blocked')}};
 assert.equal(readGainMeterEnabled(storage),false);
 assert.equal(saveGainMeterEnabled(false,storage),false);
});
