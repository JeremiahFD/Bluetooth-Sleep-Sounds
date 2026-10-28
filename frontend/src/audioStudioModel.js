/** Numeric controls and response use the same 48 kHz / Q=.7 filters as the Pi. */
export const BANDS = Object.freeze([
 {key:'eq_bass_db',frequency:125,label:'125 Hz',simple:'Low'},
 {key:'eq_lowmid_db',frequency:500,label:'500 Hz'},
 {key:'eq_mid_db',frequency:1000,label:'1 kHz',simple:'Mid'},
 {key:'eq_presence_db',frequency:4000,label:'4 kHz'},
 {key:'eq_treble_db',frequency:8000,label:'8 kHz',simple:'High'},
]);
export const visibleBands = mode => mode===5 ? BANDS : BANDS.filter(b=>b.simple);
export const clamp = (v,min,max) => Math.min(max,Math.max(min,Number.isFinite(v)?v:min));
export function quantize(value,min,max,step=1){return clamp(Number((Math.round(value/step)*step).toFixed(4)),min,max);}
export function toPosition(value,min,max,log=false){const v=clamp(Number(value),min,max);return log?Math.log(v/min)/Math.log(max/min):(v-min)/(max-min);}
export function fromPosition(p,min,max,log=false,step=1){p=clamp(p,0,1);return quantize(log?min*Math.pow(max/min,p):min+(max-min)*p,min,max,step);}
export function formatValue(value,unit='dB'){
 const v=Number(value),n=Number.isFinite(v)?Number(v.toFixed(2)):0;
 if(unit===':1')return n+':1';
 return (unit==='dB'&&n>0?'+':'')+n+(unit?' '+unit:'');
}
export function normalizedDraft(draft,ranges){
 const result={...draft};
 for(const [key,[min,max]] of Object.entries(ranges)){
  if(draft[key]===''||draft[key]===null||!Number.isFinite(Number(draft[key]))||Number(draft[key])<min||Number(draft[key])>max)
   throw new Error(key.replaceAll('_',' ')+' must be between '+min+' and '+max+'.');
  result[key]=Number(draft[key]);
 }
 if(![3,5].includes(result.eq_bands))throw new Error('Choose 3-band or 5-band EQ.');
 return result;
}
export function settingsEqual(a,b){return !!a&&!!b&&Object.keys(a).length===Object.keys(b).length&&Object.keys(a).every(k=>a[k]===b[k]);}
export function positiveBoost(settings){
 if(settings.bypass)return 0;
 const order=settings.rack_order||['gain','eq','compressor','limiter'];
 return (order.includes('gain')&&settings.gain_enabled!==false?Math.max(0,settings.gain_db||0):0)+
 (order.includes('compressor')&&settings.compressor_enabled?Math.max(0,settings.compressor_makeup_db||0):0)+
 (order.includes('eq')&&settings.eq_enabled?visibleBands(settings.eq_bands).reduce((n,b)=>n+Math.max(0,settings[b.key]||0),0):0);
}
export function needsLevelWarning(candidate,base){
 if(candidate.bypass)return false;
 return positiveBoost(candidate)>positiveBoost(base)+.0001 || (base.bypass&&!candidate.bypass&&positiveBoost(candidate)>0) ||
 (base.limiter_enabled&&!candidate.limiter_enabled&&positiveBoost(candidate)>0);
}
export function peakResponse(frequency,center,gain,q=.7,sampleRate=48000){
 if(!gain)return 0;
 const A=10**(gain/40),w0=2*Math.PI*center/sampleRate,alpha=Math.sin(w0)/(2*q),cos=Math.cos(w0);
 const b=[1+alpha*A,-2*cos,1-alpha*A],a=[1+alpha/A,-2*cos,1-alpha/A];
 const w=2*Math.PI*frequency/sampleRate;
 const magnitude=c=>Math.hypot(c[0]+c[1]*Math.cos(w)+c[2]*Math.cos(2*w),-c[1]*Math.sin(w)-c[2]*Math.sin(2*w));
 return 20*Math.log10(magnitude(b)/magnitude(a));
}
export function eqResponse(frequency,settings){
 if(!settings.eq_enabled||settings.bypass)return 0;
 return visibleBands(settings.eq_bands).reduce((db,b)=>db+peakResponse(frequency,b.frequency,Number(settings[b.key])||0),0);
}
export function newPresetId(){const bytes=new Uint8Array(16);crypto.getRandomValues(bytes);return [...bytes].map(v=>v.toString(16).padStart(2,'0')).join('');}
