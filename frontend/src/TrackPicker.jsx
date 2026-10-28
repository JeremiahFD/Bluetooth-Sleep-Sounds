import React,{useState} from 'react';
import {Dialog,Icon,nameOf} from './ui.jsx';
import {matchesSearch} from './libraryModel.js';
export default function TrackPicker({tracks,value,onChoose,onClose,allowCurrent=false}){
 const [query,setQuery]=useState(''),[descriptions,setDescriptions]=useState(false);
 const rows=tracks.filter(t=>matchesSearch(t,query,descriptions));
 return <Dialog title="Default sleep sound" icon="music" onClose={onClose}><label className="search-field"><Icon name="search" size={16}/><input autoFocus type="search" aria-label="Search default sound" value={query} onChange={e=>setQuery(e.target.value)}/></label><label className="description-choice"><input type="checkbox" checked={descriptions} onChange={e=>setDescriptions(e.target.checked)}/> Include descriptions</label><div className="track-picker">{allowCurrent&&<button className="option-row" aria-pressed={value==='@current'} onClick={()=>{onChoose('@current');onClose()}}>Last played / current track {value==='@current'&&<Icon name="check" size={16}/>}</button>}<button className="option-row" onClick={()=>{onChoose(null);onClose()}}>None {value==null&&'✓'}</button>{rows.map(t=><button className="option-row" key={t.id} aria-pressed={t.id===value} onClick={()=>{onChoose(t.id);onClose()}}><span>{nameOf(t)}</span>{value===t.id&&<Icon name="check" size={16}/>}</button>)}{!rows.length&&<p>No matching audio files.</p>}</div><p className="helper">Select a sound without starting playback.</p></Dialog>
}
