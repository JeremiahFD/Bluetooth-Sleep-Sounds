import React from 'react';
import {Icon,Toggle} from './ui.jsx';
import {saveGainMeterEnabled} from './developerSettings.js';

export default function DeveloperOptions({gainMeterEnabled,onGainMeterChange,onClose}){
 const change=value=>onGainMeterChange(saveGainMeterEnabled(value));
 return <section className="developer-page" aria-labelledby="developer-title">
  <header className="developer-header"><button type="button" className="studio-back" aria-label="Back to Settings" onClick={onClose}><Icon name="right" size={22}/></button><div><span className="eyebrow">SETTINGS</span><h1 id="developer-title">Developer options</h1></div></header>
  <section className="surface developer-card"><h2>Realtime audio animations</h2><p>Optional live feedback from the Pi while an audio page is open.</p>
   <div className="setting-row"><div><label>Gain levels</label><small>Show before and after gain peaks and the overload light.</small></div><Toggle checked={gainMeterEnabled} label="Realtime gain levels" onChange={change}/></div>
   <p className="small-info"><Icon name="info" size={15}/> Off by default. When off, the app does not request meter samples or attach a meter filter. When on, it requests readings only while the gain page is visible and audio is playing. Test for Bluetooth interruptions before relying on it overnight.</p>
  </section>
 </section>;
}
