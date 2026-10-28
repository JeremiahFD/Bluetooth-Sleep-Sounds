export const fromConfig=c=>({allow_track_deletion:c.allow_track_deletion===true,audio_buffer_ms:Math.round((c.audio_buffer_seconds??0.5)*1000),max_upload_bytes:c.max_upload_bytes/1073741824,storage_reserve_mb:c.storage_reserve_mb,auto_reconnect:c.auto_reconnect,reconnect_retry_minutes:c.reconnect_retry_minutes,resume_after_restart:c.resume_after_restart});
export function payloadFor(draft,keys){
 const result={};
 for(const key of keys){let v=draft[key];
  if(key==='max_upload_bytes'){if(v===''||!Number.isInteger(+v)||+v<1||+v>50)throw new Error('Maximum audio file size must be 1–50 GB.');v=+v*1073741824;}
  else if(key==='storage_reserve_mb'){if(v===''||!Number.isInteger(+v)||+v<0||+v>10240)throw new Error('Storage reserve must be 0–10,240 MB.');v=+v;}
  else if(key==='reconnect_retry_minutes'){if(v===''||!Number.isInteger(+v)||+v<1||+v>1440)throw new Error('Reconnect timeout must be 1–1,440 minutes.');v=+v;}
  if(key==='audio_buffer_ms'){
   if(v===''||!Number.isFinite(+v)||+v<100||+v>2000)throw new Error('Playback buffer must be 100-2000 ms.');
   result.audio_buffer_seconds=+v/1000;
  }else result[key]=v;
 }
 return result;
}
