import React,{useId,useRef} from 'react';
import {Dialog,Icon,Toggle} from './ui.jsx';
import {visibleBands,clamp,toPosition,fromPosition,quantize,formatValue,eqResponse} from './audioStudioModel.js';

export function StudioIcon({name,size=24}){
 if(name==='wave')return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" aria-hidden="true"><path d="M2 12c4-10 6-10 10 0s6 10 10 0"/></svg>;
 if(name==='voice')return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" aria-hidden="true"><circle cx="12" cy="7" r="4"/><path d="M4 22v-2a8 8 0 0 1 16 0v2"/></svg>;
 if(name==='rain')return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" aria-hidden="true"><path d="M6 15H5a4 4 0 0 1 0-8 6 6 0 0 1 11-2 5 5 0 0 1 2 10h-1M8 18l-1 3m6-3-1 3m6-3-1 3"/></svg>;
 return <Icon name={name==='levels'?'normalize':name} size={size}/>;
}
export function ValueButton({name,label,value,unit,onPrecision,disabled=false,large=false}){
 return <button type="button" className={'studio-value'+(large?' large':'')} aria-label={'Edit '+label+' value'} disabled={disabled} onClick={()=>onPrecision({name,label,unit})}>{formatValue(value,unit)}</button>;
}
const point=(angle,r)=>({x:100+Math.sin(angle*Math.PI/180)*r,y:100-Math.cos(angle*Math.PI/180)*r});
export function Knob({name,label,value,min,max,step=.5,onChange,onPrecision,disabled=false,large=false,unit='dB',showReset=true,resetValue=0}){
 const uid=useId().replaceAll(':',''),drag=useRef(null),p=toPosition(Number(value),min,max),start=point(-135,76),end=point(135,76),dot=point(-135+p*270,62);
 const arc=`M ${start.x} ${start.y} A 76 76 0 1 1 ${end.x} ${end.y}`,length=Math.PI*76*1.5;
 const set=v=>onChange(name,quantize(v,min,max,step));
 const down=e=>{if(disabled||e.button>0)return;e.preventDefault();e.currentTarget.focus();drag.current={id:e.pointerId,y:e.clientY,value:Number(value)};e.currentTarget.setPointerCapture(e.pointerId);};
 const move=e=>{const d=drag.current;if(disabled||!d||d.id!==e.pointerId)return;e.preventDefault();set(d.value+(d.y-e.clientY)*(max-min)/(large?280:220)*(e.shiftKey ? .1 : 1));};
 const up=e=>{if(drag.current?.id===e.pointerId){drag.current=null;if(e.currentTarget.hasPointerCapture(e.pointerId))e.currentTarget.releasePointerCapture(e.pointerId);}};
 const key=e=>{if(disabled)return;let v=Number(value);if(['ArrowUp','ArrowRight'].includes(e.key))v+=step;else if(['ArrowDown','ArrowLeft'].includes(e.key))v-=step;else if(e.key==='PageUp')v+=step*10;else if(e.key==='PageDown')v-=step*10;else if(e.key==='Home')v=min;else if(e.key==='End')v=max;else return;e.preventDefault();set(v);};
 return <div className={'studio-knob-control'+(large?' is-large':'')+(disabled?' disabled':'')} data-control={name}>
 <div className="studio-knob" role="slider" tabIndex={disabled?-1:0} aria-label={label} aria-valuemin={min} aria-valuemax={max} aria-valuenow={Number(value)} aria-valuetext={formatValue(value,unit)} aria-disabled={disabled} title={disabled?'Tap Edit to adjust':'Drag up or down to adjust'} onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up} onLostPointerCapture={()=>{drag.current=null}} onKeyDown={key}>
 <svg viewBox="0 0 200 200" aria-hidden="true"><defs><radialGradient id={uid+'face'} cx="32%" cy="21%" r="80%"><stop offset="0" stopColor="#333653"/><stop offset=".48" stopColor="#172338"/><stop offset="1" stopColor="#091322"/></radialGradient><linearGradient id={uid+'rim'} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#8d8daf"/><stop offset=".35" stopColor="#263a56"/><stop offset="1" stopColor="#040c16"/></linearGradient><linearGradient id={uid+'arc'} x1="0" y1="1" x2="1" y2="0"><stop stopColor="#a49ae9"/><stop offset="1" stopColor="#d0c1ff"/></linearGradient></defs>
 {Array.from({length:large?41:25},(_,i)=>{const count=large?40:24,a=-135+i*270/count,s=point(a,large?90:89),t=point(a,i%(large?5:4)===0?96:93);return <line key={i} x1={s.x} y1={s.y} x2={t.x} y2={t.y} stroke={i<=p*count?'#c1c0e8':'#53647c'} strokeWidth={i%5===0?1.3:.8} opacity={large?1:.6}/>})}
 <circle cx="102" cy="106" r="73" fill="#030914" opacity=".7"/>
 <path d={arc} fill="none" stroke="#243750" strokeWidth="6" strokeLinecap="round"/>
 <path d={arc} fill="none" stroke={'url(#'+uid+'arc)'} strokeWidth="6" strokeLinecap="round" strokeDasharray={`${Math.max(.001,p*length)} ${length}`} className="knob-arc"/>
 <circle cx="100" cy="100" r="68" fill={'url(#'+uid+'rim)'}/><circle cx="100" cy="100" r="65" fill={'url(#'+uid+'face)'} stroke="rgba(192,198,239,.14)" strokeWidth=".8"/>
 <circle cx={dot.x} cy={dot.y} r={large?4.3:4.8} fill="#f1edff" className="knob-dot"/>
 </svg></div>
 {large?<><div className="studio-gain-readout"><button className="studio-step" aria-label="Decrease gain" disabled={disabled} onClick={()=>set(Number(value)-step)}>−</button><ValueButton {...{name,label,value,unit,onPrecision,disabled}} large/><button className="studio-step" aria-label="Increase gain" disabled={disabled} onClick={()=>set(Number(value)+step)}>+</button></div><div className="studio-range-ends"><span>{min} dB</span><span>{max>0?'+':''}{max} dB</span></div></>:<div className="studio-control-foot"><ValueButton {...{name,label,value,unit,onPrecision,disabled}}/>{showReset&&<button className="studio-control-reset" type="button" aria-label={'Reset '+label} title={'Reset '+label} disabled={disabled||Number(value)===resetValue} onClick={()=>set(resetValue)}><Icon name="refresh" size={13}/></button>}</div>}
 </div>;
}
export function Slider({name,label,unit,value,range,step=1,log=false,onChange,onPrecision,disabled=false,resetValue=0}){
 const [min,max]=range,p=toPosition(Number(value),min,max,log);
 return <div className={'studio-slider'+(disabled?' disabled':'')} data-control={name}><div className="studio-slider-head"><label htmlFor={'studio-'+name}>{label}</label><div className="studio-control-foot"><ValueButton {...{name,label,unit,value,onPrecision,disabled}}/><button className="studio-control-reset" type="button" aria-label={'Reset '+label} title={'Reset '+label} disabled={disabled||Number(value)===resetValue} onClick={()=>onChange(name,resetValue)}><Icon name="refresh" size={13}/></button></div></div><input id={'studio-'+name} aria-label={label+' slider'} type="range" min="0" max="1000" step="1" value={Math.round(p*1000)} disabled={disabled} style={{'--fill':(p*100)+'%'}} onChange={e=>onChange(name,fromPosition(Number(e.target.value)/1000,min,max,log,step))}/><div className="studio-range-ends"><span>{unit===':1'?'1:1':min}</span><span>{unit===':1'?max+':1':max}</span></div></div>;
}
export function EffectHeading({title,icon,description,enabled,onToggle,onHelp,onEdit,onReset,editing=false,disabled=false}){
 return <><div className="studio-effect-heading"><div><StudioIcon name={icon}/><h2>{title}</h2><button className="studio-info" aria-label={'About '+title} title={'About '+title} onClick={onHelp}><Icon name="info" size={20}/></button></div><div className="studio-effect-actions">{onReset&&<button type="button" className="studio-control-reset" title={'Reset '+title} aria-label={'Reset '+title} disabled={disabled} onClick={onReset}><Icon name="refresh" size={15}/></button>}{onEdit&&<button type="button" className="studio-edit-button" aria-pressed={editing} disabled={disabled} onClick={onEdit}>{editing?'Done':'Edit'}</button>}{onToggle&&<Toggle label={'Enable '+title.toLowerCase()} checked={enabled} onChange={onToggle} disabled={disabled}/>}</div></div><p className="studio-description">{description}</p></>;
}
export function EqGraph({settings}){
 const uid=useId().replaceAll(':',''),left=34,right=534,top=12,bottom=174,width=right-left,height=bottom-top;
 const x=f=>left+Math.log10(f/20)/3*width,y=db=>top+(12-clamp(db,-12,12))/24*height;
 const samples=Array.from({length:181},(_,i)=>{const f=20*1000**(i/180);return {f,db:eqResponse(f,settings)}});
 const path=samples.map((s,i)=>(i?'L':'M')+x(s.f).toFixed(2)+' '+y(s.db).toFixed(2)).join(' ');
 return <figure className="studio-eq-graph"><svg viewBox="0 0 548 201" role="img" aria-label="Calculated equalizer frequency response, not a live spectrum"><defs><linearGradient id={uid} x1="0" y1="0" x2="0" y2="1"><stop stopColor="#aa91ee" stopOpacity=".32"/><stop offset="1" stopColor="#aa91ee" stopOpacity="0"/></linearGradient></defs>
 <rect x={left} y={top} width={width} height={height} fill="rgba(4,13,27,.28)"/>
 {[20,30,50,80,125,200,315,500,800,1000,2000,4000,8000,12000,20000].map(f=><line key={f} x1={x(f)} y1={top} x2={x(f)} y2={bottom} stroke="rgba(168,190,224,.12)" strokeWidth=".8"/>)}
 {[12,6,0,-6,-12].map(db=><g key={db}><line x1={left} y1={y(db)} x2={right} y2={y(db)} stroke={db===0?'rgba(185,184,229,.35)':'rgba(168,190,224,.13)'}/><text x={left-10} y={y(db)+4} textAnchor="end" className="eq-axis">{db>0?'+'+db:db}</text></g>)}
 <path d={path+` L ${right} ${bottom} L ${left} ${bottom} Z`} fill={'url(#'+uid+')'}/><path d={path} fill="none" stroke="#b9a2f5" strokeWidth="2.8"/>
 {visibleBands(settings.eq_bands).map(b=><g key={b.key}><circle cx={x(b.frequency)} cy={y(eqResponse(b.frequency,settings))} r="5.5" fill="#c8b6ff" stroke="#e5dcff" strokeWidth=".7"/><text x={x(b.frequency)} y="194" textAnchor="middle" className="eq-axis">{b.frequency>=1000?(b.frequency/1000)+"k":b.frequency}</text></g>)}
 </svg><figcaption>Frequency (Hz) · EQ response · Q 0.7{settings.bypass||!settings.eq_enabled?' · bypassed':''}</figcaption></figure>;
}
export function PrecisionDialog({control,value,range,onClose,onSet}){
 const [text,setText]=React.useState(String(value)),[error,setError]=React.useState('');
 const submit=e=>{e.preventDefault();const number=Number(text);if(text.trim()===''||!Number.isFinite(number)||number<range[0]||number>range[1]){setError('Enter a number from '+range[0]+' to '+range[1]+'.');return;}onSet(control.name,number);onClose();};
 return <Dialog title={control.label} icon="sliders" onClose={onClose} kind="studio-precision-dialog"><form onSubmit={submit}><label className="field-label">Exact value ({control.unit})<input autoFocus aria-label="Exact value" type="number" inputMode="decimal" step="any" min={range[0]} max={range[1]} value={text} onChange={e=>setText(e.target.value)}/></label><p className="helper">Drag the knob or slider for quick changes. Range: {range[0]} to {range[1]} {control.unit}.</p>{error&&<p role="alert" className="inline-error">{error}</p>}<div className="dialog-actions"><button type="button" className="secondary" onClick={onClose}>Cancel</button><button type="submit" className="primary">Set value</button></div></form></Dialog>;
}
