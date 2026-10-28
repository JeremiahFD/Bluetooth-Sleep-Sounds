import React from 'react';
export default function Rating({value,onChange,disabled=false,label='My rating'}){
 return <span className="rating-control"><span className="rating-label">{label}</span><span className="stars" role="group" aria-label={label}>{[1,2,3,4,5].map(n=><button key={n} type="button" disabled={disabled||!onChange} aria-label={label+': '+n+' star'+(n===1?'':'s')} aria-pressed={value===n} className={n<=value?'filled':''} onClick={()=>onChange(n===value?null:n)}>★</button>)}</span><small>{value==null?'Unrated':value+'/5'}</small></span>
}
