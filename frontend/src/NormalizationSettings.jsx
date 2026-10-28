import React,{useEffect,useState} from 'react';
import {Dialog,Icon,Toggle} from './ui.jsx';
import {Slider,PrecisionDialog,StudioIcon} from './AudioStudioControls.jsx';
import useLiveAudio from './useLiveAudio.js';

const PRESETS=[
 {id:'light',name:'Light',description:'Subtle evening leveling · up to about 3.5 dB boost'},
 {id:'balanced',name:'Balanced',description:'The original normalization sound · up to about 6 dB boost'},
 {id:'night',name:'Night',description:'More even quiet passages · up to about 8 dB boost'},
];

export default function NormalizationSettings({config,status,api,refresh,online,onClose,navigationGuard}){
 const alarm=status?.mode==='alarm',disabled=!online||alarm;
 const {draft:audio,saving,saved,error,dirty,edit:change,commit,reload}=useLiveAudio({config,api,refresh,enabled:!disabled});
 const draft={enabled:audio.normalization,strength:audio.normalization_strength||'balanced',ceiling:audio.normalization_ceiling_db??-1};
 const [precision,setPrecision]=useState(null),[help,setHelp]=useState(false);
 useEffect(()=>{window.scrollTo({top:0,behavior:'instant'});},[]);
 const permitClose=()=>{if(saving||dirty&&!error){commit();return false;}return !dirty||window.confirm('Discard normalization changes that could not be saved?');};
 useEffect(()=>{if(navigationGuard)navigationGuard.current=permitClose;return()=>{if(navigationGuard)navigationGuard.current=null;}},[dirty,saving,error]);
 const edit=(key,value)=>change({[{enabled:'normalization',strength:'normalization_strength',ceiling:'normalization_ceiling_db'}[key]]:value});
 return <section className="audio-studio studio-normalization" aria-labelledby="normalization-title">
  <header className="studio-header"><button className="studio-back" aria-label="Back to previous page" onClick={()=>permitClose()&&onClose()}><Icon name="right" size={25}/></button><div><h1 id="normalization-title">Normalization</h1><p>Even out quiet and loud passages.</p></div><button className="studio-reset" disabled={disabled} onClick={()=>{edit('strength','balanced');edit('ceiling',-1)}}><Icon name="refresh" size={19}/><span>Reset</span></button></header>
  <section className="studio-glass studio-normalization-main"><div className="studio-normalization-switch"><div><h2>Audio normalization</h2><p>Gently level the track while you listen. Your recording stays unchanged.</p></div><Toggle label="Audio normalization" checked={draft.enabled} disabled={disabled} onChange={v=>edit('enabled',v)}/></div>
  <div className="studio-presets-heading"><span>LEVELING PRESETS</span><small>Select a starting point</small></div><div className="studio-normalization-presets">{PRESETS.map(p=><button type="button" key={p.id} className={'studio-preset-card'+(draft.strength===p.id?' selected':'')} aria-pressed={draft.strength===p.id} disabled={disabled} onClick={()=>edit('strength',p.id)}><StudioIcon name="levels" size={25}/><strong>{p.name}</strong><small>{p.description}</small></button>)}</div>
  <div className="studio-normalization-ceiling"><Slider name="normalization_ceiling_db" label="Output ceiling" unit="dBFS" value={draft.ceiling} range={config?.audio_processing_ranges?.normalization_ceiling_db||[-12,0]} step={.1} onChange={(name,value)=>edit('ceiling',value)} onPrecision={setPrecision} resetValue={-1} disabled={disabled}/><p>Caps sample peaks after leveling. A lower ceiling leaves more headroom.</p></div>
  <button className="studio-tip" onClick={()=>setHelp(true)}><Icon name="info" size={19}/><span>Normalization and manual gain, EQ and dynamics take turns. Switching normalization on keeps your manual settings for later.</span></button></section>
  {alarm&&<p className="studio-banner">Dismiss the alarm before changing normalization.</p>}{!online&&<p className="studio-banner">Reconnect to the Pi before applying settings.</p>}{error&&<p className="studio-banner error" role="alert">{error} <button className="text-button" onClick={()=>commit()}>Retry</button> <button className="text-button" onClick={reload}>Reload saved settings</button></p>}
  <div className="studio-apply-bar"><div className="studio-apply-status" role="status">{saving?'Applying to Pi…':saved?'Applied and saved on Pi':dirty?'Changes pending…':'Saved settings'}<small>Changes apply automatically. Keep editing while they save.</small></div><button className="studio-apply-button" disabled={disabled||saving||!dirty} onClick={commit}><Icon name="check" size={18}/>{saving?'Applying…':'Apply settings'}</button></div>
  {precision&&<PrecisionDialog control={precision} value={draft.ceiling} range={config?.audio_processing_ranges?.normalization_ceiling_db||[-12,0]} onSet={(_,value)=>edit('ceiling',value)} onClose={()=>setPrecision(null)}/>}
  {help&&<Dialog title="About normalization" icon="info" onClose={()=>setHelp(false)}><p>Light, Balanced and Night change how much the Pi evens out volume. The output ceiling limits digital sample peaks. These controls do not repair clipping already present in a file or inside a speaker.</p><p>The app saves manual effect settings separately. Turning normalization off lets you return to them.</p></Dialog>}
 </section>;
}
