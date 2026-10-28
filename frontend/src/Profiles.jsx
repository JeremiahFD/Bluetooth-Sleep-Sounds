import React,{useEffect,useRef,useState} from 'react';
import {Dialog,Icon,IconButton,Toggle} from './ui.jsx';
import './profiles.css';

import {shouldPromptForProfile,rememberProfileEnabled} from './profileSession.js';
const KEY = 'sleep-profile-id';
const nativeSession=(()=>{try{const url=new URL(window.location.href),session=url.searchParams.get('native_session');if(/SleepSoundsAndroid\//.test(navigator.userAgent)&&session&&/^[a-f0-9-]{36}$/.test(session)){sessionStorage.setItem('sleep-native-session',session);if(url.searchParams.get('native_confirmed')==='1')sessionStorage.setItem('sleep-profile-confirmed',session);url.searchParams.delete('native_session');url.searchParams.delete('native_confirmed');history.replaceState(history.state,'',url);return session}return sessionStorage.getItem('sleep-native-session')||'browser'}catch{return 'browser'}})();
function sessionConfirmed(){try{return sessionStorage.getItem('sleep-profile-confirmed')===nativeSession}catch{return false}}
function confirmSession(){try{sessionStorage.setItem('sleep-profile-confirmed',nativeSession)}catch{}}
export function readSavedProfileId(){try{const url=new URL(window.location.href),native=url.searchParams.get('native_profile');if(/SleepSoundsAndroid\//.test(navigator.userAgent)&&native&&(native==='none'||/^[a-f0-9]{16}$/.test(native))){localStorage.setItem(KEY,native);url.searchParams.delete('native_profile');history.replaceState(history.state,'',url)}return localStorage.getItem(KEY)}catch{return null}}

/** Selection belongs to this browser/WebView; the Pi stores each profile's data. */
export default function ProfileControl({api,profileId,onSelect,onChanged=()=>{},online=true,hiddenTrigger=false,onBrowse}){
 const prompted=useRef(false);
 const [remember,setRemember]=useState(()=>{try{return rememberProfileEnabled(localStorage)}catch{return true}});
 const [catalog,setCatalog]=useState(null),[open,setOpen]=useState(false),[error,setError]=useState('');
 const [busy,setBusy]=useState(false),[adding,setAdding]=useState(false),[name,setName]=useState('');
 const [editing,setEditing]=useState(null),[deleting,setDeleting]=useState(null);
 useEffect(()=>{let alive=true;api.profiles().then(data=>{if(!alive)return;setCatalog(data);
   if(data.enabled&&!prompted.current){prompted.current=true;if(shouldPromptForProfile({enabled:data.enabled,valid:data.profiles.some(p=>p.id===profileId),remember,saved:readSavedProfileId(),confirmed:sessionConfirmed()}))setOpen(true);}
 }).catch(()=>{});return()=>{alive=false}},[api,online]);
 useEffect(()=>{const show=()=>{api.profiles().then(setCatalog).catch(e=>setError(e.message));setOpen(true);setError('')};window.addEventListener('sleep-open-profiles',show);
   return()=>window.removeEventListener('sleep-open-profiles',show)},[]);
 useEffect(()=>{const missing=()=>{try{localStorage.removeItem(KEY)}catch{};onSelect('none');setOpen(true);
    api.profiles().then(setCatalog).catch(()=>{});};
   window.addEventListener('sleep-profile-missing',missing);
   return()=>window.removeEventListener('sleep-profile-missing',missing)},[api,onSelect]);
 const effective=catalog?.enabled?profileId:'none';
 const current=catalog?.profiles?.find(p=>p.id===effective)?.name||'None';
 const choose=id=>{confirmSession();try{localStorage.setItem(KEY,id)}catch{};api.setProfileId(id);onSelect(id);onChanged();window.dispatchEvent(new Event('sleep-profiles-changed'));setOpen(false);setError('')};
 const mutate=async(action,details={})=>{setBusy(true);setError('');try{
   const next=await api.changeProfile(action,details);setCatalog(next);onChanged();window.dispatchEvent(new Event('sleep-profiles-changed'));
   if(action==='add'){setAdding(false);setName('')}
   if(action==='rename')setEditing(null);
   if(action==='enabled'&&!details.enabled){try{sessionStorage.removeItem('sleep-profile-confirmed')}catch{};api.setProfileId('none');onSelect('none')}
   if(action==='enabled'&&details.enabled)prompted.current=true;
   if(action==='delete'){
     setDeleting(null);
     if(profileId===details.profile){try{localStorage.removeItem(KEY)}catch{};api.setProfileId('none');onSelect('none');
       if(next.enabled)setOpen(true)}
   }
 }catch(e){setError(e.message||'Could not save profiles.')}finally{setBusy(false)}};
 return <>
  {!hiddenTrigger&&<button type="button" className="profile-trigger" onClick={()=>{setOpen(true);setError('')}} aria-label={'Current profile '+current+'. Open profiles'}>
   <Icon name="settings" size={16}/><span>{current}</span><Icon name="chevron" size={14}/>
  </button>}
  {open&&<Dialog title="Profiles" icon="settings" onClose={()=>setOpen(false)} kind="profiles-dialog">
   <div className="profile-toggle"><div><strong>Use profiles</strong><small>Each profile keeps its own favorites and preferences.</small></div>
    <Toggle checked={!!catalog?.enabled} disabled={!online||busy||!catalog||catalog.read_error} label="Use profiles" onChange={enabled=>mutate('enabled',{enabled})}/></div>
   <label className="remember-profile"><input type="checkbox" checked={remember} onChange={e=>{setRemember(e.target.checked);try{localStorage.setItem('sleep-remember-profile',String(e.target.checked))}catch{}}}/> Remember me on this device</label>
   {catalog?.read_error&&<p className="inline-warning" role="alert">Profile data needs repair on the Pi. The saved file has been left untouched.</p>}
   {!catalog?<p>Loading profiles…</p>:<div className="profile-list" aria-label="Saved profiles">
    {catalog.profiles.map(p=><div className={'profile-row'+(p.id===effective?' selected':'')+(catalog.enabled||p.id==='none'?'':' profile-disabled')} key={p.id}>
     {editing===p.id?<form onSubmit={e=>{e.preventDefault();mutate('rename',{profile:p.id,name})}} className="profile-edit-form">
       <input autoFocus aria-label="Profile name" maxLength="32" value={name} onChange={e=>setName(e.target.value)}/>
       <button type="submit" disabled={busy||!name.trim()}>Save</button>
       <button type="button" className="secondary compact" onClick={()=>setEditing(null)}>Cancel</button>
      </form>:<>
       <button type="button" className="profile-choice" disabled={!online||busy||(!catalog.enabled&&p.id!=='none')}
         aria-pressed={p.id===effective} onClick={()=>choose(p.id)}>
        <span className="profile-avatar">{p.id==='none'?'–':p.name[0].toUpperCase()}</span><span>{p.name}</span>{p.id===effective&&<Icon name="check" size={17}/>}</button>
       {p.id!=='none'&&<div className="profile-actions">
        <IconButton icon="edit" label={'Edit '+p.name} disabled={!catalog.enabled||busy} onClick={()=>{setEditing(p.id);setName(p.name)}}/>
        <IconButton icon="close" label={'Delete '+p.name} disabled={!catalog.enabled||busy} onClick={()=>setDeleting(p)}/>
       </div>}</>}
    </div>)}
   </div>}
   {catalog?.enabled&&<div className="profile-add">
    {adding?<form onSubmit={e=>{e.preventDefault();mutate('add',{name})}}>
      <input autoFocus aria-label="New profile name" maxLength="32" value={name} onChange={e=>setName(e.target.value)} placeholder="Profile name"/>
      <button type="submit" disabled={!online||busy||!name.trim()}>Add</button>
      <button type="button" className="secondary compact" onClick={()=>{setAdding(false);setName('')}}>Cancel</button>
     </form>:<button type="button" className="secondary profile-add-button" onClick={()=>{setAdding(true);setName('')}} disabled={!online||busy}><Icon name="plus" size={18}/> Add profile</button>}
   </div>}
   {onBrowse&&<button className="secondary compact" onClick={()=>{setOpen(false);onBrowse()}}>View favorites, ratings &amp; stats</button>}
   {deleting&&<div className="profile-delete-confirm" role="alertdialog" aria-label={'Delete '+deleting.name}>
    <p>Delete <strong>{deleting.name}</strong> and its saved favorites and settings?</p>
    <div className="dialog-actions"><button type="button" className="secondary compact" onClick={()=>setDeleting(null)}>Cancel</button>
     <button type="button" className="danger compact" disabled={busy} onClick={()=>mutate('delete',{profile:deleting.id})}>Delete profile</button></div></div>}
   {error&&<p role="alert" className="inline-warning">{error}</p>}
  </Dialog>}
 </>;
}
