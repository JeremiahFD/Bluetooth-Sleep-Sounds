/** Same-origin adapter shared by all future React layouts; Pi remains authoritative. */
export class SleepSoundsApi {
  constructor(fetcher = globalThis.fetch.bind(globalThis)) {
    this.fetch = fetcher; this.token = null; this.profileId = 'none'; this.audioChain=Promise.resolve();this.audioMutationEpoch=0;
    this.editorSession=globalThis.crypto?.randomUUID?.()||('audio-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2));
  }
  queueAudio(task) { const next=this.audioChain.catch(()=>{}).then(task);this.audioChain=next;return next; }
  setProfileId(id) { this.profileId = id || 'none'; }
  async request(path, body) {
    if (!path.startsWith('/api/')) throw new Error('Unsupported API path');
    const profileActions = new Set(['/api/play','/api/select-track','/api/sleep','/api/favorite','/api/settings',
      '/api/play_mode','/api/normalization','/api/audio-processing','/api/rating','/api/feedback','/api/track-comments']);
    if (body !== undefined && profileActions.has(path)) body = {...body, profile:this.profileId};
    if (body !== undefined && !this.token) await this.status();
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), body === undefined ? 12000 : 25000);
    let response, result;
    try {
      response = await this.fetch(path, body === undefined ? {signal:controller.signal} : {
        method: 'POST', headers: { 'X-Sleep-Token': this.token, 'Content-Type': 'application/json' },
        body: JSON.stringify(body), signal:controller.signal
      });
      result = await response.json();
    } catch (error) {
      if (error?.name === 'AbortError') throw new Error('The Pi did not respond in time. Check its connection, then try again.');
      throw error;
    } finally {
      clearTimeout(timer);
    }
    if (response.status === 403) this.token = null;
    if (!response.ok) {const error=new Error(result.error || `Pi returned ${response.status}`);error.status=response.status;throw error;}
    if (path === '/api/status') this.token = result.csrf;
    if(body!==undefined&&['/api/settings','/api/audio-processing','/api/normalization','/api/play',
      '/api/select-track','/api/sleep','/api/pause','/api/stop','/api/next','/api/previous','/api/output','/api/play_mode'].includes(path))this.audioMutationEpoch++;
    return result;
  }
  status() { return this.request('/api/status'); }
  async tracks() {
    try { return await this.request('/api/tracks?profile=' + encodeURIComponent(this.profileId)); }
    catch (error) {
      if (!/profile is no longer available/i.test(error.message)) throw error;
      this.setProfileId('none');
      globalThis.window?.dispatchEvent(new Event('sleep-profile-missing'));
      return this.request('/api/tracks?profile=none');
    }
  }
  libraryCatalog() { return this.request('/api/library-catalog'); }
  editMetadata(track,values,revision) { return this.request('/api/library-metadata',{track,values,revision}); }
  changeTags(action,details) { return this.request('/api/library-catalog',{action,...details}); }
  rating(track,rating) { return this.request('/api/rating',{track,rating}); }
  publicProfile(profile) { return this.request('/api/public-profile?profile='+encodeURIComponent(profile)); }
  feedback() { return this.request('/api/feedback'); }
  postFeedback(body,url='',parent=null) { return this.request('/api/feedback',{body,url,parent}); }
  trackComments(track) { return this.request('/api/track-comments?track='+encodeURIComponent(track)); }
  postTrackComment(track,body,parent=null) { return this.request('/api/track-comments',{track,body,parent}); }
  deleteTrack(track) { return this.request('/api/track-delete',{track,confirm:true}); }
  diagnostics() { return this.request('/api/diagnostics-export'); }
  system() { return this.request('/api/system'); }
  systemAction(action,confirmation) { return this.request('/api/system-action',{action,confirm:true,confirmation}); }
  appRelease() { return this.request('/api/app-release'); }
  profileDataFor(profile) { return this.request('/api/profile-data?profile='+encodeURIComponent(profile)); }
  saveProfilePreferences(profile,preferences) { return this.request('/api/profile-data',{profile,preferences}); }
  profiles() { return this.request('/api/profiles'); }
  remotes() { return this.request('/api/remotes'); }
  remoteAction(action, details={}) { return this.request('/api/remotes', {action,...details}); }
  profileData() { return this.request('/api/profile-data?profile=' + encodeURIComponent(this.profileId)); }
  updateProfileData(preferences) { return this.request('/api/profile-data', {profile:this.profileId, preferences}); }
  changeProfile(action, details={}) { return this.request('/api/profiles', {action,...details}); }
  trackDetails(track) { return this.request('/api/track-details?track=' + encodeURIComponent(track) + '&profile=' + encodeURIComponent(this.profileId)); }
  librarySummary() { return this.request('/api/library-summary?profile=' + encodeURIComponent(this.profileId)); }
  audioMeter() { return this.request('/api/audio-meter', {}); }
  outputs() { return this.request('/api/outputs'); }
  config() { return this.request('/api/config?profile=' + encodeURIComponent(this.profileId)); }
  alarm() { return this.request('/api/alarm'); }
  play(track) { return this.request('/api/play', {track}); }
  selectTrack(track) { return this.request('/api/select-track', {track}); }
  sleep(track, minutes) { return this.request('/api/sleep', {track, minutes}); }
  pause(paused) { return this.request('/api/pause', paused===undefined?{}:{paused}); }
  stop() { return this.request('/api/stop', {}); }
  timer(minutes) { return this.request('/api/timer', {minutes}); }
  timerEnd(time) { return this.request('/api/timer_end', {time}); }
  playMode(mode) { return this.request('/api/play_mode', {mode}); }
  next() { return this.request('/api/next', {}); }
  previous() { return this.request('/api/previous', {}); }
  seek(seconds) { return this.request('/api/seek', {seconds}); }
  favorite(track, favorite) { return this.request('/api/favorite', {track, favorite}); }
  normalization(enabled) { return this.queueAudio(()=>this.request('/api/normalization', {enabled,editor_session:this.editorSession})); }
  audioProcessing(settings, expected_revision) { return this.queueAudio(()=>this.request('/api/audio-processing', {settings, expected_revision,editor_session:this.editorSession})); }
  saveLiveAudio(patch) { return this.queueAudio(async()=>{
    const {normalization,...settings}=patch;
    let result;
    if(Object.keys(settings).length)result=await this.request('/api/audio-processing',{settings,editor_session:this.editorSession});
    if(normalization!==undefined)result=await this.request('/api/normalization',{enabled:normalization,editor_session:this.editorSession});
    // New servers acknowledge the saved values in the same transaction.
    return result?.audio_processing?{...result,audio_processing_revision:result.audio_processing_revision??result.revision}:this.config();
  }); }
  audioEditLock() { return this.request('/api/audio-edit-lock?editor_session='+encodeURIComponent(this.editorSession)); }
  configureAudioEditLock(enabled,timeout_seconds) { return this.request('/api/audio-edit-lock',{action:'configure',enabled,timeout_seconds,editor_session:this.editorSession}); }
  releaseAudioEditLock() { return this.request('/api/audio-edit-lock',{action:'release',editor_session:this.editorSession}); }
  audioPresets() { return this.request('/api/audio-presets'); }
  saveAudioPreset(payload) { return this.request('/api/audio-presets', payload); }
  settings(values) { return ('volume' in values||'audio_buffer_seconds' in values)?this.queueAudio(()=>this.request('/api/settings', {...values,editor_session:this.editorSession})):this.request('/api/settings', values); }
  speakerSync(values) { return this.request('/api/speaker-sync', values); }
  output(name) { return this.request('/api/output', {name}); }
  configureAlarm(values) { return this.request('/api/alarm', values); }
  bluetooth(action, address, confirm = false) { return this.request('/api/bluetooth', {action, address, confirm}); }
  pairing(id, approve, value = null) { return this.request('/api/pairing', {id, approve, value}); }
  uploadWithProgress(file, onProgress = () => {}, uploadKey = null) {
    return this.sendFileWithProgress('/api/upload?name=' + encodeURIComponent(file.name) + (uploadKey?'&key='+encodeURIComponent(uploadKey):''), file, onProgress, uploadKey);
  }
  uploadThumbnailWithProgress(track, file, onProgress = () => {}) {
    return this.sendFileWithProgress('/api/artwork?track=' + encodeURIComponent(track) + '&name=' + encodeURIComponent(file.name), file, onProgress);
  }
  sendFileWithProgress(path, file, onProgress = () => {}, uploadKey = null) {
    const xhr = new XMLHttpRequest();
    let cancelled=false;
    const promise = (async () => {
      if (!this.token) await this.status();
      if(cancelled)throw new Error('Upload cancelled.');
      if(uploadKey){const prior=await this.request('/api/upload-result?key='+encodeURIComponent(uploadKey));if(cancelled)throw new Error('Upload cancelled.');if(prior.complete){onProgress(100);return {id:prior.id,reused:true};}}
      return new Promise((resolve, reject) => {
        xhr.open('POST', path, true);
        xhr.setRequestHeader('X-Sleep-Token', this.token);
        xhr.upload.onprogress = event => {
          if (event.lengthComputable && event.total > 0) onProgress(Math.min(100, Math.round(event.loaded / event.total * 100)));
        };
        xhr.onload = () => {
          let result;
          try { result = JSON.parse(xhr.responseText); }
          catch { return reject(new Error('The Pi returned an unreadable upload response.')); }
          if (xhr.status === 403) this.token = null;
          if (xhr.status >= 200 && xhr.status < 300) resolve(result);
          else reject(new Error(result.error || 'Upload failed. Check the Pi and try again.'));
        };
        xhr.onerror = () => reject(new Error('Connection lost during upload. Check your Wi-Fi and try again.'));
        xhr.onabort = () => reject(new Error('Upload cancelled.'));
        xhr.send(file);
      });
    })();
    return {promise, abort: () => {cancelled=true;xhr.abort();}};
  }  async upload(file) {
    if (!this.token) await this.status();
    const response = await this.fetch(`/api/upload?name=${encodeURIComponent(file.name)}`, {
      method: 'POST', headers: {'X-Sleep-Token': this.token}, body: file
    });
    const result = await response.json();
    if (response.status === 403) this.token = null;
    if (!response.ok) throw new Error(result.error || 'Upload failed');
    return result;
  }
}
