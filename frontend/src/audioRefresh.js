/** Status polling is cheap; fetch only config when another client edits audio.
 * A delayed status response must not roll a newer acknowledged config backward.
 * A server restart is handled separately by the full-refresh instance guard. */
export function needsAudioConfigRefresh(status,config){
 if(!config)return true;
 const incoming=status?.audio_processing_revision,current=config.audio_processing_revision;
 if(Number.isInteger(incoming)&&(!Number.isInteger(current)||incoming>current))return true;
 return Number.isFinite(status?.volume)&&status.volume!==config.volume;
}

/** Reject reads that began before this client's acknowledged audio mutation.
 * The refresh owner retries them; stale reads must not undo a saved control.
 * This does not send settings or suppress changes made by another client. */
export async function readAudioSnapshot(api,read){
 const epoch=api.audioMutationEpoch;
 const value=await read();
 return {value,current:epoch===api.audioMutationEpoch};
}
