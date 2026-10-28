import React,{useEffect,useState} from 'react';
import {Toggle} from './ui.jsx';

export default function AudioEditLock({api,visible,config,profiles}){
 const [lock,setLock]=useState(null),[timeout,setTimeoutValue]=useState(60),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const load=async()=>{try{const data=await api.audioEditLock();setLock(data);setTimeoutValue(data.timeout_seconds);setError('');}catch(e){setError(e.message);}};
 useEffect(()=>{if(visible&&config?.audio_edit_lock)load();},[visible,api,!!config?.audio_edit_lock]);
 const configure=async(enabled,seconds)=>{
  if(!Number.isInteger(+seconds)||+seconds<15||+seconds>3600){setError('Choose an inactivity timeout from 15 to 3600 seconds.');return;}
  setBusy(true);setError('');try{setLock(await api.configureAudioEditLock(enabled,+seconds));}catch(e){setError(e.message);}finally{setBusy(false);}
 };
 if(!config?.audio_edit_lock)return null;
 const current=lock||config.audio_edit_lock;
 const owner=profiles?.profiles?.find(p=>p.id===current.owner_profile)?.name;
 return <div className="audio-edit-lock">
  <div className="setting-row"><div><label>Lock audio editing to one session</label><small>Off allows everyone to adjust the current playback.</small></div><Toggle label="Lock audio editing to one session" checked={!!current.enabled} disabled={busy} onChange={enabled=>configure(enabled,timeout)}/></div>
  <label className="compact-field">Release after inactivity<div><input aria-label="Audio edit lock inactivity timeout" type="number" min="15" max="3600" step="1" disabled={!current.enabled||busy} value={timeout} onChange={e=>setTimeoutValue(e.target.value)} onBlur={()=>{if(current.enabled&&+timeout!==current.timeout_seconds)configure(true,timeout)}}/><span>seconds</span></div></label>
  {current.enabled&&<p className="helper">{current.locked?(current.owned?'This session is editing audio.':(owner||'Another session')+' is editing audio. The lock releases automatically after inactivity.'):'The next audio adjustment takes the lock.'} <button className="text-button" disabled={busy} onClick={load}>Refresh</button>{current.owned&&<button className="text-button" disabled={busy} onClick={async()=>{setBusy(true);try{setLock(await api.releaseAudioEditLock());}catch(e){setError(e.message);}finally{setBusy(false);}}}>Release now</button>}</p>}
  {error&&<p className="inline-error" role="alert">{error}</p>}
 </div>;
}
