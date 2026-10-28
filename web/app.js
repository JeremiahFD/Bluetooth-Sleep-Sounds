'use strict';
const $ = id => document.getElementById(id);
let state = null, tracks = [], selected = null, polling = false, outputRefresh = 0, uploading = false, offline = false, trackSignature = '', deviceSignature = '';
const time = seconds => { const s = Math.max(0, Math.floor(seconds || 0)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; };
function error(message) { $('error').textContent = message; $('error').hidden = !message; }
async function api(path, data) {
  const options = data === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json','X-Sleep-Token':state?.csrf || ''}, body:JSON.stringify(data)};
  const response = await fetch(`/api/${path}`, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'The Pi could not complete that action.');
  return result;
}
async function act(path, data) {
  try { error(''); await api(path, data); await refresh(); }
  catch (e) { error(e.message); }
}
function renderTracks() {
  const signature=JSON.stringify([tracks, selected]);
  if(signature===trackSignature)return;
  trackSignature=signature;
  const list = $('tracks'); list.replaceChildren(); $('track-count').textContent = tracks.length;
  if (!tracks.length) { const li = document.createElement('li'); li.className='empty'; li.textContent='No sounds yet. Add your first rain or storm recording above.'; list.append(li); }
  for (const track of tracks) {
    const li=document.createElement('li'), button=document.createElement('button'), icon=document.createElement('span'), text=document.createElement('span'), size=document.createElement('small');
    button.className = `track${selected === track.id ? ' active' : ''}`;
    button.setAttribute('aria-pressed', String(selected === track.id));
    icon.className='track-icon'; icon.textContent='♪'; icon.setAttribute('aria-hidden','true');
    text.className='track-text'; text.textContent=track.name; size.textContent=`${(track.bytes / 1048576).toFixed(1)} MB · ${track.id.split('.').pop().toUpperCase()}`;
    text.append(size); button.append(icon,text); button.addEventListener('click',()=>{selected=track.id; act('play',{track:track.id});}); li.append(button); list.append(li);
  }
}
function render() {
  const track=tracks.find(t=>t.id === (state.selected || selected));
  if (state.selected) selected=state.selected;
  $('connection').textContent=state.preview ? 'Design preview' : 'Pi connected'; $('power').hidden=!state.power.undervoltage;
  $('now-title').textContent=track?.name || 'Make room for rest.';
  $('now-detail').textContent=track ? (state.idle ? 'Ready to play on your Raspberry Pi.' : state.paused ? 'Paused on your Raspberry Pi.' : 'Playing on your Raspberry Pi.') : 'Upload a rain or storm recording to get started.';
  $('playback-state').textContent=state.idle ? 'READY WHEN YOU ARE' : state.paused ? 'PAUSED' : 'SETTLE IN';
  $('play').textContent=state.idle ? 'Play' : state.paused ? 'Resume' : 'Pause';
  $('play').disabled=!selected || !state.output_ready; $('stop').disabled=state.idle;
  if(state.playback_error)error(state.playback_error);
  $('elapsed').textContent=time(state.position); $('duration').textContent=time(state.duration);
  $('progress').max=state.duration || 1; $('progress').value=state.position;
  $('loop').checked=state.loop;
  if (document.activeElement !== $('volume')) { $('volume').value=state.volume; $('volume-value').textContent=`${state.volume}%`; }
  $('timer-state').textContent=state.timer_seconds === null ? 'Off' : `${time(state.timer_seconds)} left`;
  $('cancel-timer').hidden=state.timer_seconds === null;
  $('scan').disabled=state.bluetooth.busy; $('scan').textContent=state.bluetooth.busy ? 'Working…' : 'Find speaker';
  $('bluetooth-status').textContent=state.bluetooth.message;
  const nextDevices=JSON.stringify([state.bluetooth.devices,state.bluetooth.busy]);
  if(nextDevices!==deviceSignature){
  deviceSignature=nextDevices;
  const devices=$('devices'); devices.replaceChildren();
  for (const device of state.bluetooth.devices) {
    const li=document.createElement('li'), title=document.createElement('span'), detail=document.createElement('small'), button=document.createElement('button');
    title.textContent=device.name; detail.textContent=device.connected ? 'Connected' : device.paired ? 'Paired' : 'Available'; title.append(detail);
    button.textContent=device.connected ? 'Disconnect' : 'Connect'; button.disabled=state.bluetooth.busy;
    button.addEventListener('click',()=>act('bluetooth',{action:device.connected?'disconnect':'connect',address:device.address})); li.append(title,button); devices.append(li);
  }}
  renderTracks();
}
async function outputs() {
  const info=await api('outputs');
  if (document.activeElement === $('output')) return;
  $('output').replaceChildren();
  const placeholder=document.createElement('option'); placeholder.value=''; placeholder.textContent='Choose speaker or audio output'; placeholder.disabled=true; $('output').append(placeholder);
  for (const item of info.devices) { const option=document.createElement('option'); option.value=item.name; option.textContent=item.description || item.name; $('output').append(option); }
  $('output').value=info.selected || '';
}
async function refresh() {
  if (polling) return;
  polling=true;
  try {
    state=await api('status'); if(offline){error('');offline=false;} render();
    if (Date.now()-outputRefresh>12000) { tracks=await api('tracks'); renderTracks(); await outputs(); outputRefresh=Date.now(); }
  } catch(e) { offline=true; $('connection').textContent='Pi unavailable'; error(`Connection lost: ${e.message} Reconnecting automatically…`); }
  finally { polling=false; }
}
$('play').addEventListener('click',()=>state && (state.idle ? act('play',{track:selected}) : act('pause',{})));
$('stop').addEventListener('click',()=>act('stop',{}));
$('loop').addEventListener('change',()=>act('settings',{loop:$('loop').checked}));
$('volume').addEventListener('input',()=>{$('volume-value').textContent=`${$('volume').value}%`;});
$('volume').addEventListener('change',()=>act('settings',{volume:Number($('volume').value)}));
document.querySelectorAll('[data-minutes]').forEach(button=>button.addEventListener('click',()=>act('timer',{minutes:Number(button.dataset.minutes)})));
$('timer-form').addEventListener('submit',event=>{event.preventDefault();act('timer',{minutes:Number($('minutes').value)});});
$('cancel-timer').addEventListener('click',()=>act('timer',{minutes:0}));
$('scan').addEventListener('click',()=>act('bluetooth',{action:'scan'}));
$('output').addEventListener('change',()=>act('output',{name:$('output').value}));
$('upload').addEventListener('change',async()=>{
  if (uploading || !state) return;
  uploading=true; $('upload').disabled=true; error('');
  try {
    for (const file of $('upload').files) {
      if (file.size>512*1024*1024) throw new Error(`${file.name} exceeds the 512 MB limit.`);
      await new Promise((resolve,reject)=>{
        const request=new XMLHttpRequest(); request.open('POST',`/api/upload?name=${encodeURIComponent(file.name)}`);
        request.setRequestHeader('X-Sleep-Token',state.csrf); request.timeout=15*60*1000;
        request.upload.onprogress=e=>{$('upload-status').textContent=`Uploading ${file.name}${e.lengthComputable ? ` · ${Math.round(e.loaded/e.total*100)}%` : ''}`;};
        request.onload=()=>{if(request.status===201)resolve();else{try{reject(new Error(JSON.parse(request.responseText).error));}catch{reject(new Error('Upload failed.'));}}};
        request.onerror=()=>reject(new Error('Upload interrupted. Check the connection and retry.'));
        request.ontimeout=()=>reject(new Error('Upload timed out. Please retry.')); request.send(file);
      });
    }
    tracks=await api('tracks'); if(!selected && tracks.length)selected=tracks[0].id;
    $('upload-status').textContent='Added to your sounds.'; renderTracks(); await refresh();
  }catch(e){error(e.message);$('upload-status').textContent='';}
  finally{uploading=false;$('upload').disabled=false;$('upload').value='';}
});
async function boot() {
  try { tracks=await api('tracks'); if(tracks.length)selected=tracks[0].id; await refresh(); }
  catch(e){error(e.message);}
}
boot(); setInterval(()=>{if(!document.hidden)refresh();},2500);
document.addEventListener('visibilitychange',()=>{if(!document.hidden){boot();outputRefresh=0;}});
