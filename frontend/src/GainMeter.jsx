import React,{useEffect,useState} from 'react';

const EMPTY={available:false,input_peak_dbfs:null,gain_stage_peak_dbfs:null,output_peak_dbfs:null,gain_clipping:false,output_clipping:false};
const width=value=>value==null?'0%':Math.max(0,Math.min(100,(value+24)/30*100))+'%';
const level=value=>value==null?'—':(value>0?'+':'')+value.toFixed(1)+' dBFS';

export default function GainMeter({api,online,status,dirty=false,enabled=false}){
 const [reading,setReading]=useState(EMPTY),[held,setHeld]=useState(false),[error,setError]=useState('');
 useEffect(()=>{if(!enabled){setReading(EMPTY);setHeld(false);setError('')}},[enabled]);
 useEffect(()=>{
  if(!enabled||!online||status?.idle||status?.paused||status?.mode==='idle'||status?.mode==='alarm')return;
  let live=true,timer=null,hold=null;
  const poll=async()=>{
   if(!live)return;
   if(document.visibilityState==='hidden'){
    setReading(EMPTY);timer=setTimeout(poll,500);return;
   }
   try{
    const data=await api.audioMeter();
    if(!live)return;
    setReading(data?.available?data:EMPTY);setError('');
    if(data?.gain_clipping){setHeld(true);clearTimeout(hold);hold=setTimeout(()=>live&&setHeld(false),1200);}
   }catch(e){if(live){setReading(EMPTY);setError('Meter unavailable. Audio playback is unaffected.');}}
   if(live)timer=setTimeout(poll,250);
  };
  poll();
  return()=>{live=false;clearTimeout(timer);clearTimeout(hold);};
 },[api,enabled,online,status?.mode,status?.idle,status?.paused]);
 const rows=[['Chain input',reading.input_peak_dbfs],['After gain (estimate)',reading.gain_stage_peak_dbfs],['Chain output',reading.output_peak_dbfs]];
 return <div className="studio-gain-meter" role="group" aria-label="Live audio peak levels">
  <div className="studio-meter-heading"><strong>Live levels</strong><small>{enabled?'On':'Off'}</small></div>
  {rows.map(([label,value])=><div className="studio-meter-group" key={label}><div className="studio-meter-row"><span>{label}</span><small>{enabled?level(value):'—'}</small></div><div className="studio-meter-track" aria-hidden="true"><div className="studio-meter-fill" style={{width:enabled?width(value):'0%'}}/><i className="studio-meter-zero"/></div><div className="studio-meter-ticks" aria-hidden="true"><span>−24</span><span>−12</span><span>−6</span><span>0</span><span>+6</span></div></div>)}
  <div className="studio-overload"><span className={'studio-overload-dot'+(enabled&&held?' lit':'')} aria-hidden="true"/><span role="status">{enabled&&held?'Overload risk':'No overload detected'}</span></div>
  <p className="studio-meter-help">Chain input and output are measured on the host. The gain estimate is available only with Gain first in the rack. The red line marks 0 dBFS.{dirty?' Apply edits to measure the new setting.':''}</p>
  {!enabled?<small className="studio-meter-unavailable">Realtime gain is off in Settings → Developer options.</small>:!reading.available&&<small className="studio-meter-unavailable">{error||(status?.idle?'Start playback to see live levels.':'Waiting for audio levels…')}</small>}
 </div>;
}
