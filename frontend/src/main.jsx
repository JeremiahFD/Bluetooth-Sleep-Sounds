import {AndroidEffects,AndroidSettings,AndroidDevices} from './AndroidHostPages.jsx';
import {CloudstormControlsGallery} from './CloudstormControls.jsx';
import React,{useCallback,useEffect,useRef,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {SleepSoundsApi} from './api.js';
import {needsAudioConfigRefresh,readAudioSnapshot} from './audioRefresh.js';
import {Icon,IconButton,Dialog,Artwork,nameOf,countdown} from './ui.jsx';
import NowPlaying,{TimerDialog,PlayerOptions} from './NowPlaying.jsx';
import Library from './Library.jsx';
import {browsingPreferences,miniPlayerTrack,shouldShowMiniPlayer} from './browsingPreferences.js';
import Settings from './Settings.jsx';
import AudioProcessing from './AudioProcessing.jsx';
import DeveloperOptions from './DeveloperOptions.jsx';
import Remotes from './Remotes.jsx';
import Explore from './Explore.jsx';
import Community from './Community.jsx';
import TagsSettings from './TagsSettings.jsx';
import SystemSettings from './SystemSettings.jsx';
import AppUpdates from './AppUpdates.jsx';
import './discovery.css';
import {readGainMeterEnabled} from './developerSettings.js';
import ProfileControl,{readSavedProfileId} from './Profiles.jsx';
import TrackDetails from './TrackDetails.jsx';
import {resolveTheme,nativeOwnsInsets} from './themes.js';
import {AlarmPage,DevicesPage} from './DevicePages.jsx';
import './style.css';
import './roadmap.css';
import './audio-studio.css';
import './next-build.css';
document.documentElement.dataset.nativeInsets=String(nativeOwnsInsets(navigator.userAgent));
const api=new SleepSoundsApi();
api.setProfileId(readSavedProfileId()||'none');
const PAGES=[['home','Now Playing','moon'],['library','Library','music'],['explore','Explore','leaf'],['alarm','Alarm','alarm'],['devices','Devices','device'],['settings','Settings','sliders']];
function App(){
 const [route,setRoute]=useState(()=>window.history.state?.sleepRoute||{page:'home',panel:window.location.hash==='#audio'?'audio':null});
 const {page, panel}=route;
 const [categoryRequest,setCategoryRequest]=useState(null),[profilePreferences,setProfilePreferences]=useState({}),[preferencesProfile,setPreferencesProfile]=useState(null),[preferencesLoadError,setPreferencesLoadError]=useState('');
 const [profileId,setProfileId]=useState(()=>readSavedProfileId()||'none');
 const [gainMeterEnabled,setGainMeterEnabled]=useState(readGainMeterEnabled);
 const [details,setDetails]=useState(null),[librarySummary,setLibrarySummary]=useState(null);
 const [theme,setTheme]=useState(()=>{try{const t=localStorage.getItem('sleep-theme');return resolveTheme(t).id}catch{return 'moonlit'}});
 const [status,setStatus]=useState(null),[tracks,setTracks]=useState([]),[config,setConfig]=useState(null),[outputs,setOutputs]=useState({devices:[],selected:''}),[alarm,setAlarm]=useState(null),[selected,setSelected]=useState('');
 const [online,setOnline]=useState(false),[error,setError]=useState(''),[pending,setPending]=useState(new Set()),[pairCode,setPairCode]=useState('');
 const [sampleTime,setSampleTime]=useState(performance.now()),[now,setNow]=useState(performance.now());
 const skipNextPopGuard=useRef(false);
 const routeUrl=next=>{const url=new URL(window.location.href);url.hash=['audio','normalization'].includes(next.panel)?'audio':'';return url;};
 const pushRoute=next=>{const depth=(window.history.state?.sleepDepth||0)+1;window.history.pushState({sleepRoute:next,sleepDepth:depth},'',routeUrl(next));setRoute(next);};
 const setPanel=next=>pushRoute({...route,panel:next});
 const setPage=next=>pushRoute({page:next,panel:null});
 const closePanel=()=>{if((window.history.state?.sleepDepth||0)>0){skipNextPopGuard.current=true;window.history.back()}else{const next={...route,panel:null};window.history.replaceState({sleepRoute:next,sleepDepth:0},'',routeUrl(next));setRoute(next)}};
 useEffect(()=>{if(!window.history.state?.sleepRoute)window.history.replaceState({sleepRoute:route,sleepDepth:0},'',routeUrl(route));const onPop=e=>{const alreadyConfirmed=skipNextPopGuard.current;skipNextPopGuard.current=false;if(!alreadyConfirmed&&audioGuard.current&&!audioGuard.current()){window.history.forward();return;}setRoute(e.state?.sleepRoute||{page:'home',panel:null});};window.addEventListener('popstate',onPop);return()=>window.removeEventListener('popstate',onPop)},[]);
 const audioGuard=useRef(null);
 const mounted=useRef(true),inFlight=useRef(false),requestedFull=useRef(false),lastFull=useRef(0),lastRevision=useRef(null),lastInstance=useRef(null),lastConfig=useRef(null),pendingRef=useRef(new Set()),previousBusy=useRef(false),first=useRef(true);
 const refresh=useCallback(async(full=false)=>{
  if(inFlight.current){requestedFull.current ||=full;return;}
  inFlight.current=true;
  try{
   const snapshot=await readAudioSnapshot(api,()=>api.status());if(!mounted.current)return;
   if(!snapshot.current){requestedFull.current=true;return;}
   const s=snapshot.value;
   setStatus(s);setSampleTime(performance.now());setOnline(true);
   const reload=full||first.current||s.csrf!==lastInstance.current||s.library_revision!==lastRevision.current||performance.now()-lastFull.current>10000||(previousBusy.current&&!s.bluetooth?.busy);
   previousBusy.current=!!s.bluetooth?.busy;lastInstance.current=s.csrf;lastRevision.current=s.library_revision;
   if(reload){
    const requestedProfile=api.profileId;
    const snapshot=await readAudioSnapshot(api,()=>Promise.all([api.tracks(),api.config(),api.outputs(),api.alarm(),api.librarySummary().catch(()=>null)]));if(!mounted.current)return;if(!snapshot.current||api.profileId!==requestedProfile){requestedFull.current=true;return;}
    const [t,c,o,a,l]=snapshot.value;
    setTracks(t);setConfig(c);lastConfig.current=c;setOutputs(o);setAlarm(a);lastFull.current=performance.now();
    setLibrarySummary(l);
    setSelected(old=>t.some(x=>x.id===old)?old:(t.some(x=>x.id===s.selected)?s.selected:t[0]?.id||''));first.current=false;
   }else if(needsAudioConfigRefresh(s,lastConfig.current)){
    const requestedProfile=api.profileId,snapshot=await readAudioSnapshot(api,()=>api.config());
    if(!mounted.current)return;
    if(!snapshot.current||api.profileId!==requestedProfile){requestedFull.current=true;return;}
    lastConfig.current=snapshot.value;setConfig(snapshot.value);
   }
  }catch(e){if(mounted.current)setOnline(false);}
  finally{inFlight.current=false;if(requestedFull.current&&mounted.current){requestedFull.current=false;queueMicrotask(()=>refresh(true));}}
 },[]);
 useEffect(()=>{mounted.current=true;refresh(true);const poll=setInterval(()=>{if(document.visibilityState==='visible')refresh()},1600);const tick=setInterval(()=>setNow(performance.now()),1000);const wake=()=>{if(document.visibilityState==='visible')refresh(true)};document.addEventListener('visibilitychange',wake);addEventListener('focus',wake);return()=>{mounted.current=false;clearInterval(poll);clearInterval(tick);document.removeEventListener('visibilitychange',wake);removeEventListener('focus',wake)}},[refresh]);
 useEffect(()=>{let active=true;setPreferencesProfile(null);setPreferencesLoadError('');
   api.profileDataFor(profileId).then(data=>{if(active){setProfilePreferences(data.preferences||{});setPreferencesProfile(profileId);if(data?.preferences?.theme)setTheme(resolveTheme(data.preferences.theme).id)}})
     .catch(e=>{if(active){setPreferencesLoadError(e.message||'Could not load profile preferences.');setProfilePreferences({})}});
   return()=>{active=false}},[profileId]);
 const currentPreferences=preferencesProfile===profileId?profilePreferences:null;
 const browseSettings=browsingPreferences(currentPreferences);
 const saveBrowsingPreference=async(key,value)=>{
   if(!['open_now_playing_on_select','show_mini_player','fullscreen_layout'].includes(key)||typeof value!=='boolean')throw new Error('Invalid browsing preference.');
   const id=profileId;
   const saved=await api.saveProfilePreferences(id,{[key]:value});
   if(api.profileId===id){setProfilePreferences(old=>({...old,...(saved.preferences||{}),[key]:value}));setPreferencesProfile(id);}
   return saved;
 };
 useEffect(()=>{try{localStorage.setItem('sleep-theme',theme)}catch{}document.documentElement.dataset.theme=theme;const meta=document.querySelector('meta[name=theme-color]');if(meta)meta.content=resolveTheme(theme).color},[theme]);
 const changeTheme=id=>{setTheme(id);api.updateProfileData({theme:id}).catch(e=>setError(e.message||'Could not save theme to the Pi.'))};
 const selectProfile=id=>{try{localStorage.setItem('sleep-profile-id',id)}catch{}setPreferencesProfile(null);api.setProfileId(id);setProfileId(id);refresh(true)};
 const run=async(key,fn)=>{if(pendingRef.current.has(key))return false;pendingRef.current.add(key);setPending(new Set(pendingRef.current));setError('');try{await fn();await refresh(true);return true;}catch(e){setError(e.message||'The Pi could not complete that action.');return false;}finally{pendingRef.current.delete(key);if(mounted.current)setPending(new Set(pendingRef.current));}};
 const favorite=async t=>{if(!t)return;const ok=await run('favorite:'+t.id,()=>api.favorite(t.id,!t.favorite));if(ok)setTracks(old=>old.map(x=>x.id===t.id?{...x,favorite:!t.favorite}:x));};
 const showDetails=async track=>{if(!track)return;setDetails({track,loading:true,details:null,error:''});try{const result=await api.trackDetails(track.id);setDetails(old=>old?.track.id===track.id?{track,loading:false,details:result,error:''}:old)}catch(e){setDetails(old=>old?.track.id===track.id?{track,loading:false,details:null,error:e.message||'Could not load audio details.'}:old)}};
  const playFile=async t=>{const ok=await run('playback',()=>api.play(t.id));if(ok){setSelected(t.id);setPage('home')}};
  const selectLibraryFile=async t=>{const openAfterSelection=browseSettings.openNowPlayingOnSelect;const ok=await run('playback',()=>api.selectTrack(t.id));if(ok){setSelected(t.id);if(openAfterSelection)setPage('home')}};
 const elapsed=Math.max(0,(now-sampleTime)/1000),remaining=status?.timer_seconds==null?null:Math.max(0,status.timer_seconds-elapsed);
 const rawPosition=(status?.position||0)+(online&&!status?.idle&&!status?.paused?elapsed:0);
 const position=status?.duration?Math.min(status.duration,rawPosition):rawPosition;
 const activeTrack=tracks.find(t=>t.id===status?.selected),miniTrack=miniPlayerTrack(status,tracks,selected),deviceName=outputs.devices?.find(d=>d.name===outputs.selected)?.description||'No device selected';
 const navigate=id=>{if(['audio','normalization','remotes'].includes(panel)&&audioGuard.current&&!audioGuard.current())return;setPage(id);setError('');window.scrollTo({top:0,behavior:'instant'});};
 const pairing=status?.pairing?.pending;const androidHost=status?.platform==='android';const SettingsPage=androidHost?AndroidSettings:Settings;
 return <div className={'app theme-'+theme+' screen-'+page+(currentPreferences?.fullscreen_layout===true?' fullscreen-layout':'')+(['audio','normalization'].includes(panel)?' audio-studio-open':'')}><div className="ambient-background" aria-hidden="true"/><a className="skip-link" href="#main-content">Skip to content</a><aside className="rail"><a className="brand" href="#" onClick={e=>{e.preventDefault();navigate('home')}}><span className="brand-mark"><Icon name="moon" size={24}/></span><span>Sleep Sounds<small>YOUR QUIET SPACE</small></span></a><nav aria-label="Main navigation">{PAGES.map(([id,label,icon])=><button key={id} className={(['audio','normalization'].includes(panel)?'settings':page)===id?'current':''} aria-current={(['audio','normalization'].includes(panel)?'settings':page)===id?'page':undefined} onClick={()=>navigate(id)}><Icon name={icon} size={19}/><span>{label}</span></button>)}</nav><div className="rail-bottom"><span className={'connection '+(online?'online':'')}><i/>{online?'Connected to host':'Host unreachable'}</span><small>Audio stays on the selected host.<br/>Local controls and remote access.</small></div></aside>
 <main id="main-content" className="main"><header className="topbar"><div className="mobile-brand"><Icon name="moon" size={20}/> Sleep Sounds</div><span className="breadcrumb">{PAGES.find(p=>p[0]===page)?.[1]}</span><div className="top-actions"><ProfileControl api={api} profileId={profileId} hiddenTrigger onBrowse={()=>setPanel('profiles')} onSelect={selectProfile} onChanged={()=>refresh(true)} online={online}/>{remaining!=null&&<button className="top-timer" onClick={()=>setPanel('timer')} aria-label="Open running sleep timer"><Icon name="moon" size={14}/>{countdown(remaining)}</button>}<span className={'connection '+(online?'online':'')} title={deviceName}><i/>{online?'Connected':'Offline'}</span><IconButton icon="refresh" label="Refresh connection" onClick={()=>refresh(true)}/></div></header>
 {!online&&status&&<div className="banner warning" role="status"><Icon name="warning" size={17}/><span>Cannot reach the Pi. Local audio may still be playing; controls will return when the connection does.</span><button onClick={()=>refresh(true)}>Retry</button>{/SleepSoundsAndroid\//.test(navigator.userAgent)&&<a className="text-button" href="sleep-sounds://reconnect">Try LAN / mesh</a>}</div>}
 {error&&<div className="banner error" role="alert"><Icon name="warning" size={17}/><span>{error}</span><IconButton icon="close" label="Dismiss error" onClick={()=>setError('')}/></div>}
 {androidHost&&<div className="preview-badge">Android host · local playback · some Pi features unavailable</div>}{status?.preview&&<div className="preview-badge"><Icon name="info" size={13}/> Design preview · simulated playback</div>}
 <div className="standard-pages" hidden={['audio','normalization','developer','remotes','profiles','feedback','tags','system','updates'].includes(panel)}>
 {page==='home'&&<NowPlaying status={status} config={config} tracks={tracks} selected={selected} setSelected={setSelected} theme={theme} api={api} run={run} pending={pending} refresh={refresh} onTimer={()=>setPanel('timer')} onOptions={()=>setPanel('options')} onLibrary={()=>navigate('library')} onRate={t=>async value=>{await run('rating',()=>api.rating(t.id,value))}} showEveryoneRatings={currentPreferences?.show_everyone_ratings===true} onDetails={showDetails} remaining={remaining} position={position} favorite={favorite} online={online}/>}
 <Library visible={page==='library'} tracks={tracks} summary={librarySummary} theme={theme} api={api} run={run} refresh={refresh} config={config} online={online} selected={selected} setSelected={setSelected} onPlay={playFile} onSelectTrack={selectLibraryFile} onDetails={showDetails} favorite={favorite} pending={pending} profileId={profileId} categoryRequest={categoryRequest}/>
 <Explore api={api} tracks={tracks} visible={page==='explore'} onCategory={id=>{setCategoryRequest({id,nonce:Date.now()});navigate('library')}}/>
 {(!androidHost||page==='settings')&&<SettingsPage visible={page==='settings'} config={config} status={status} api={api} refresh={refresh} theme={theme} setTheme={changeTheme} profileId={profileId} uiPreferences={currentPreferences} preferencesLoadError={preferencesLoadError} onUiPreferenceChange={saveBrowsingPreference} online={online} onProfileSelect={selectProfile} onAudio={()=>setPanel('audio')} onNormalization={()=>setPanel('normalization')} onProfiles={()=>window.dispatchEvent(new Event('sleep-open-profiles'))} onDeveloper={()=>setPanel('developer')} onRemotes={()=>setPanel('remotes')} onBrowseProfiles={()=>setPanel('profiles')} onTags={()=>setPanel('tags')} onFeedback={()=>setPanel('feedback')} onSystem={()=>setPanel('system')} onUpdates={()=>setPanel('updates')}/>}
 {androidHost?(page==='alarm'&&<section className="surface discovery-card"><h1>Alarm</h1><p>Android alarms are not yet implemented. Use a separate wake-up alarm for this test build.</p></section>):<AlarmPage visible={page==='alarm'} alarm={alarm} outputs={outputs} status={status} tracks={tracks} run={run} api={api}/>}
 {androidHost?(page==='devices'&&<AndroidDevices/>):<DevicesPage visible={page==='devices'} outputs={outputs} status={status} api={api} run={run} online={online}/>}
 {shouldShowMiniPlayer(page,status,miniTrack,currentPreferences)&&<div className="mini-player"><button className="mini-player-track" onClick={()=>navigate('home')}><Artwork theme={theme} src={miniTrack.artwork}/><span><strong>{nameOf(miniTrack)}</strong><small>{status.idle?'Ready to play':status.paused?'Paused':'Playing on host'}</small></span></button><IconButton icon={status.idle||status.paused?'play':'pause'} label={status.idle?'Play selected audio':status.paused?'Resume playback':'Pause playback'} disabled={!online||pending.has('playback')} onClick={()=>run('playback',()=>status.idle?api.play(miniTrack.id):api.pause(!status.paused))}/><IconButton icon="moon" label="Open sleep timer" active={remaining!=null} onClick={()=>setPanel('timer')}/><IconButton icon="stop" label="Stop playback" disabled={!online||status.idle||pending.has('stop')} onClick={()=>run('stop',()=>api.stop())}/></div>}
 <footer>Sleep Sounds <span>·</span> Made for quieter nights</footer></div>
 {(panel==='audio'||panel==='normalization')&&(androidHost?<AndroidEffects config={config} status={status} api={api} refresh={refresh} online={online} onClose={closePanel}/>:<AudioProcessing key={panel} page={panel} config={config} status={status} api={api} refresh={refresh} online={online} onClose={closePanel} navigationGuard={audioGuard} gainMeterEnabled={gainMeterEnabled}/>)}
 {panel==='developer'&&<DeveloperOptions gainMeterEnabled={gainMeterEnabled} onGainMeterChange={setGainMeterEnabled} onClose={closePanel}/>}
 {panel==='remotes'&&<Remotes api={api} tracks={tracks} onClose={closePanel} navigationGuard={audioGuard}/>}
 {['profiles','feedback'].includes(panel)&&<Community key={panel} page={panel} api={api} profileId={profileId} onClose={closePanel} onEdit={()=>window.dispatchEvent(new Event('sleep-open-profiles'))}/>}
 {panel==='tags'&&<TagsSettings api={api} onClose={closePanel} onChanged={()=>refresh(true)}/>}
 {panel==='system'&&<SystemSettings api={api} onClose={closePanel}/>}
 {panel==='updates'&&<AppUpdates api={api} onClose={closePanel}/>}
 </main>
 <nav className="bottom-nav" aria-label="Mobile navigation">{PAGES.map(([id,label,icon])=><button key={id} className={(['audio','normalization'].includes(panel)?'settings':page)===id?'current':''} aria-current={(['audio','normalization'].includes(panel)?'settings':page)===id?'page':undefined} onClick={()=>navigate(id)}><Icon name={icon} size={20}/><span>{id==='home'?'Player':label}</span></button>)}</nav>
 {panel==='timer'&&<TimerDialog status={status} remaining={remaining} api={api} run={run} onClose={closePanel}/>}
 {panel==='options'&&<PlayerOptions refresh={refresh} showEveryoneRatings={currentPreferences?.show_everyone_ratings===true} onRatingsChange={async value=>{const id=profileId;const ok=await run('rating-options',()=>api.saveProfilePreferences(id,{show_everyone_ratings:value}));if(ok)setProfilePreferences(old=>({...old,show_everyone_ratings:value}))}} status={status} config={config} remaining={remaining} api={api} run={run} onClose={closePanel} onTimer={()=>setPanel('timer')} onAudio={()=>setPanel('audio')} onNormalization={()=>setPanel('normalization')}/>}
 {details&&<TrackDetails {...details} theme={theme} api={api} profileId={profileId} online={online} onClose={()=>setDetails(null)}/>}
 {pairing&&<Dialog title="Confirm Bluetooth pairing" icon="bluetooth" onClose={()=>run('pairing',()=>api.pairing(pairing.id,false))}><p>{pairing.name} <small>({pairing.address})</small></p>{pairing.kind==='confirm'&&<div className="pairing-number">{pairing.code}</div>}{['pin','passkey'].includes(pairing.kind)&&<label className="field-label">Device PIN<input value={pairCode} inputMode="numeric" onChange={e=>setPairCode(e.target.value.replace(/[^0-9]/g,''))}/></label>}<p className="helper">Only approve a device you are currently pairing.</p><div className="dialog-actions"><button className="secondary compact" onClick={()=>run('pairing',()=>api.pairing(pairing.id,false))}>Reject</button><button className="primary compact" onClick={()=>run('pairing',()=>api.pairing(pairing.id,true,pairCode))}>Approve</button></div></Dialog>}
 </div>
}
createRoot(document.getElementById('root')).render(new URLSearchParams(window.location.search).get('components')==='cloudstorm'?<CloudstormControlsGallery/>:<App/>);
