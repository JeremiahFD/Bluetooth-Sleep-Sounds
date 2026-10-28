export function settingsPayload(draft){
 if(!Number.isInteger(draft.uploadGb)||draft.uploadGb<1||draft.uploadGb>50)throw new Error('Maximum audio file size must be 1–50 GB.');
 if(!Number.isInteger(draft.reserveMb)||draft.reserveMb<0||draft.reserveMb>10240)throw new Error('Free storage reserve must be 0–10,240 MB.');
 if(!Number.isInteger(draft.reconnectMinutes)||draft.reconnectMinutes<1||draft.reconnectMinutes>1440)throw new Error('Reconnect timeout must be 1–1,440 minutes.');
 return {max_upload_bytes:draft.uploadGb*1073741824,storage_reserve_mb:draft.reserveMb,
  auto_reconnect:!!draft.autoReconnect,reconnect_retry_minutes:draft.reconnectMinutes,
  resume_after_restart:!!draft.resumeAfterRestart};
}
export function settingsPersisted(config,payload){
 return Object.entries(payload).every(([key,value])=>config[key]===value);
}
