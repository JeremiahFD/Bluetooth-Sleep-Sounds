import React,{useEffect,useId,useRef,useState} from 'react';
import {resolveTheme} from './themes.js';

const shapes={
 left:<path d="m15 18-6-6 6-6"/>,
 cloud:<><path d="M7 18H6a4 4 0 0 1-1-7.87A6 6 0 0 1 16.65 8H17a5 5 0 0 1 0 10h-1"/><path d="m12 14-2 4h4l-2 4"/></>,
 home:<><path d="m3 10 9-7 9 7"/><path d="M5 9v12h5v-7h4v7h5V9"/></>,
 music:<><path d="M9 18V5l11-2v13M9 9l11-2"/><ellipse cx="6" cy="18" rx="3" ry="2"/><ellipse cx="17" cy="16" rx="3" ry="2"/></>,
 moon:<path d="M20.9 13.1A9 9 0 0 1 10.9 3 9 9 0 1 0 20.9 13.1Z"/>,
 sliders:<><path d="M4 7h4m4 0h8M4 17h9m4 0h3"/><path d="M8 4v6m4-3H8m5 7v6m4-3h-4"/></>,
 shuffle:<><path d="M3 7h3c5 0 6 10 11 10h4M17 13l4 4-4 4M3 17h3c2 0 3-2 4-4M14 8c1-1 2-1 3-1h4M17 3l4 4-4 4"/></>,
 previous:<><path d="M5 5v14"/><path d="m19 5-10 7 10 7Z" fill="currentColor" stroke="none"/></>,
 next:<><path d="M19 5v14"/><path d="m5 5 10 7-10 7Z" fill="currentColor" stroke="none"/></>,
 play:<path d="m8 4 12 8-12 8Z" fill="currentColor" stroke="none"/>,
 pause:<><rect x="6" y="4" width="4" height="16" rx="1" fill="currentColor" stroke="none"/><rect x="14" y="4" width="4" height="16" rx="1" fill="currentColor" stroke="none"/></>,
 stop:<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" stroke="none"/>,
 loop:<><path d="M18 3l3 3-3 3M3 11V9a3 3 0 0 1 3-3h15M6 21l-3-3 3-3M21 13v2a3 3 0 0 1-3 3H3"/></>,
 volume:<><path d="M3 9v6h4l5 4V5L7 9H3Z"/><path d="M16 8a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14"/></>,
 mute:<><path d="M3 9v6h4l5 4V5L7 9H3Z"/><path d="m17 9 5 6m0-6-5 6"/></>,
 heart:<path d="M20.7 4.8a5.5 5.5 0 0 0-7.8 0L12 5.9l-.9-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.7-8.4a5.5 5.5 0 0 0 0-7.8Z"/>,
 clock:<><circle cx="12" cy="12" r="9"/><path d="M12 7v5l4 2"/></>,
 hourglass:<><path d="M7 3h10M7 21h10M8 3v5l8 8v5M16 3v5l-8 8v5"/></>,
 alarm:<><circle cx="12" cy="13" r="8"/><path d="M12 8v5l3 2M5 3 2 6m17-3 3 3M6 20l-1 2m13-2 1 2"/></>,
 bluetooth:<path d="m7 7 10 10-5 4V3l5 4L7 17"/>,
 device:<><rect x="5" y="2" width="14" height="20" rx="3"/><circle cx="12" cy="14" r="4"/><path d="M11 6h2"/></>,
 settings:<><path d="m9 3 1-1h4l1 3 2 1 3-.5 2 3-2 2v3l2 2-2 3-3-.5-2 1-1 3h-4l-1-3-2-1-3 .5-2-3 2-2v-3l-2-2 2-3 3 .5 2-1Z"/><circle cx="12" cy="12" r="3"/></>,
 chevron:<path d="m7 10 5 5 5-5"/>,
 right:<path d="m9 5 7 7-7 7"/>,
 close:<path d="m6 6 12 12M18 6 6 18"/>,
 more:<><circle cx="12" cy="5" r="1.6" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1.6" fill="currentColor" stroke="none"/><circle cx="12" cy="19" r="1.6" fill="currentColor" stroke="none"/></>,
 plus:<path d="M12 5v14M5 12h14"/>,
 check:<path d="m4 12 5 5L20 6"/>,
 edit:<><path d="m15 4 5 5M4 20l4-1 12-12a2.8 2.8 0 0 0-4-4L4 15v5Z"/></>,
 search:<><circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/></>,
 image:<><rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1.5"/><path d="m3 17 5-5 4 4 4-7 5 6"/></>,
 upload:<><path d="M12 16V3m-5 5 5-5 5 5M3 16v5h18v-5"/></>,
 refresh:<><path d="M20 7v5h-5M4 17v-5h5"/><path d="M5.6 7a7 7 0 0 1 11.9-2L20 8M4 16l2.5 3A7 7 0 0 0 18.4 17"/></>,
 info:<><circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/></>,
 warning:<><path d="m12 3 10 18H2Z"/><path d="M12 9v5m0 3h.01"/></>,
 normalize:<><path d="M4 9v6M8 5v14M12 8v8M16 3v18M20 8v8"/></>,
 link:<><path d="m9 15 6-6M8 7l2-2a5 5 0 0 1 7 7l-2 2M16 17l-2 2a5 5 0 0 1-7-7l2-2"/></>,
 lock:<><rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></>,
 leaf:<><path d="M20 3C4 3 1 12 6 17s14-1 14-14Z"/><path d="M4 21 15 10"/></>,
 layers:<><path d="m12 3 10 5-10 5L2 8Zm-10 9 10 5 10-5M2 16l10 5 10-5"/></>
};
export function Icon({name,size=20,filled=false,...props}){return <svg width={size} height={size} viewBox="0 0 24 24" fill={filled?'currentColor':'none'} stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false" {...props}>{shapes[name]||shapes.info}</svg>}
export function IconButton({icon,label,active=false,children,...props}){return <button type="button" className={'icon-btn'+(active?' is-active':'')} title={label} aria-label={label} {...props}><Icon name={icon} filled={icon==='heart'&&active}/>{children}</button>}
export function Toggle({checked,onChange,label,disabled=false}){return <button type="button" className="switch" role="switch" aria-checked={!!checked} aria-label={label} disabled={disabled} onClick={()=>onChange(!checked)}><span/></button>}
export function Info({children,label='More information'}){return <details className="info-details"><summary aria-label={label} title={label}><Icon name="info" size={16}/><span className="sr-only">{label}</span></summary><div>{children}</div></details>}
export function Dialog({title,icon,children,onClose,kind=''}){
 const ref=useRef(null),id=useId();
 useEffect(()=>{const el=ref.current,previous=document.activeElement;el.showModal();return()=>{el.close();previous?.focus?.();}},[]);
 useEffect(()=>{const back=()=>{const open=[...document.querySelectorAll('dialog[open]')];if(open.at(-1)===ref.current)onClose()};window.addEventListener('sleep-back',back);return()=>window.removeEventListener('sleep-back',back)},[onClose]);
 return <dialog ref={ref} className={'dialog '+kind} aria-labelledby={id} onCancel={e=>{e.preventDefault();onClose();}} onClick={e=>{if(e.target===ref.current){const b=e.currentTarget.getBoundingClientRect();if(e.clientX<b.left||e.clientX>b.right||e.clientY<b.top||e.clientY>b.bottom)onClose();}}}><header className="dialog-head"><h2 id={id}>{icon&&<Icon name={icon}/>} {title}</h2><IconButton icon="close" label={'Close '+title} onClick={onClose}/></header>{children}</dialog>
}
export function Artwork({src,theme='moonlit',className='',alt='',...props}){
 const [failedUrls,setFailedUrls]=useState([]);useEffect(()=>setFailedUrls([]),[src,theme]);
 const fallback=resolveTheme(theme).artwork;const url=[src,fallback].find(candidate=>candidate&&!failedUrls.includes(candidate))||null;
 return <span className={'artwork '+className+(!src?' is-theme-source':'')} {...props}>{url?<img src={url} alt={alt} onError={()=>setFailedUrls(old=>old.includes(url)?old:[...old,url])} draggable="false"/>:<span className={'theme-art '+theme}><span className="art-orb"/><span className="art-ridge back"/><span className="art-ridge"/></span>}</span>
}
export function FilePreview({file,theme}){const [url,setUrl]=useState(null);useEffect(()=>{if(!file){setUrl(null);return;}const u=URL.createObjectURL(file);setUrl(u);return()=>URL.revokeObjectURL(u)},[file]);return <Artwork src={url} theme={theme} alt={file?'Selected thumbnail preview':''}/>}
export function nameOf(file){return String(file?.name||file?.id?.replace(/\.[^.]+$/,'')||'').replace(/_/g,' ').replace(/\s+/g,' ').trim();}
export function timeOf(seconds){let n=Math.max(0,Math.floor(Number(seconds)||0));const h=Math.floor(n/3600);return (h?h+':':'')+String(Math.floor(n/60)%60).padStart(h?2:1,'0')+':'+String(n%60).padStart(2,'0');}
export function countdown(seconds){const m=Math.max(0,Math.ceil((seconds||0)/60));return String(Math.floor(m/60)).padStart(2,'0')+'h '+String(m%60).padStart(2,'0')+'m';}
export function bytesOf(n){if(!Number.isFinite(n))return '—';if(n>=1073741824)return (n/1073741824).toFixed(1)+' GB';if(n>=1048576)return (n/1048576).toFixed(1)+' MB';return Math.ceil(n/1024)+' KB';}
export function Empty({icon='music',title,children}){return <div className="empty-state"><Icon name={icon} size={30}/><h3>{title}</h3><p>{children}</p></div>}
export function Heading({eyebrow,title,children,action}){return <header className="page-heading"><div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1>{children&&<p>{children}</p>}</div>{action}</header>}
