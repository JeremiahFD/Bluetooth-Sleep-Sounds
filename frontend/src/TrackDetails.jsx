import React from 'react';
import {Artwork,Dialog,Icon,nameOf,timeOf,bytesOf} from './ui.jsx';
import './track-details.css';
import TrackComments from './TrackComments.jsx';

function rate(value){return Number.isFinite(value)?`${Number(value).toLocaleString()} Hz`:'Unavailable'}
function bitrate(value){return Number.isFinite(value)?`${Number(value).toLocaleString()} kbps`:'Unavailable'}
function valueOr(value,unit=''){return Number.isFinite(value)?`${Number(value).toLocaleString()}${unit}`:'Unavailable'}

/** Reused by Library and Now Playing. Parent owns fetch/loading state. */
export default function TrackDetails({track,details,theme='moonlit',loading=false,error='',onClose,api,profileId='none',online=true}){
 if(!track)return null;
 const facts=details?.audio||details||{};
 const stats=details?.stats||{};
 const names=details?.favorited_by||[];
 const rows=[
  ['Length',Number.isFinite(facts.duration_seconds)?timeOf(facts.duration_seconds):'Unavailable'],
  ['Format',facts.format||track.id?.split('.').pop()?.toUpperCase()||'Unavailable'],
  ['Codec',facts.codec?.toUpperCase()||'Unavailable'],
  ['Bitrate',bitrate(facts.bitrate_kbps)],
  ['Bit depth',valueOr(facts.bit_depth_bits,' bit')],
  ['Sample rate',rate(facts.sample_rate_hz)],
  ['Channels',facts.channels===1?'Mono':facts.channels===2?'Stereo':valueOr(facts.channels)],
  ['File size',bytesOf(facts.size_bytes??track.bytes)],
 ];
 return <Dialog title="Audio details" icon="info" kind="track-details-dialog" onClose={onClose}>
  <div className="track-details-head"><Artwork theme={theme} src={track.artwork}/><div><strong>{nameOf(track)}</strong><small>{facts.container||'Saved on your Pi'}</small></div></div>
  {loading?<p className="helper" role="status">Reading audio details…</p>:error?<p className="inline-error" role="alert">{error}</p>:<>
   <dl className="track-details-grid">{rows.map(([label,value])=><div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
   <div className="track-details-stats"><h3><Icon name="play" size={16}/> Listening</h3><dl><div><dt>Total plays</dt><dd>{valueOr(stats.play_count)}</dd></div><div><dt>Total listening time</dt><dd>{Number.isFinite(stats.play_time_seconds)?timeOf(stats.play_time_seconds):'Unavailable'}</dd></div><div><dt>This profile’s plays</dt><dd>{valueOr(stats.profile_play_count)}</dd></div><div><dt>This profile’s listening time</dt><dd>{Number.isFinite(stats.profile_play_time_seconds)?timeOf(stats.profile_play_time_seconds):'Unavailable'}</dd></div></dl></div>
   <div className="track-details-favorites"><h3><Icon name="heart" size={16}/> Favorited by</h3><p>{names.length?names.join(', '):'No profiles yet'}</p></div>
  </>}
  {api&&<TrackComments key={track.id+':'+profileId} track={track.id} api={api} online={online}/>}
 </Dialog>
}
