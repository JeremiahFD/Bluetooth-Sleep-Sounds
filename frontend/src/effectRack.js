export const EFFECTS=Object.freeze({gain:'Gain',eq:'Equalizer',compressor:'Compressor',limiter:'Limiter',echo:'Echo'});
export const LEGACY_ORDER=['gain','eq','compressor','limiter'];
export function rackOrder(value){return Array.isArray(value)?value.filter((v,i)=>Object.hasOwn(EFFECTS,v)&&value.indexOf(v)===i):[...LEGACY_ORDER]}
export function moveEffect(order,id,before){
 if(!order.includes(id)||!order.includes(before)||id===before)return [...order];
 const next=order.filter(v=>v!==id);next.splice(next.indexOf(before),0,id);return next;
}
export function effectEnabled(id,draft){return draft[id+'_enabled']!==false && (id==='gain'||draft[id+'_enabled']===true)}
