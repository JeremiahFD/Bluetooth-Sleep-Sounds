import React,{useState} from 'react';
import {Icon} from './ui.jsx';
import './cloudstorm-controls.css';

import {CloudstormButton} from './CloudstormButton.jsx';

export function CloudstormControlsGallery(){
 const [enabled,setEnabled]=useState(false),[message,setMessage]=useState('Try a control. This gallery has no connection to the player.');
 return <div className="app theme-cloudstorm"><div className="ambient-background" aria-hidden="true"/><main className="cloudstorm-gallery">
 <a href="/ui/#audio">Back to effects rack</a><h1>Cloudstorm controls</h1><p>Generated artwork experiment. Real labels, icons, keyboard focus and disabled states.</p>
 <section className="surface"><h2>Action buttons</h2><div className="cloudstorm-gallery-row"><CloudstormButton variant="primary" onClick={()=>setMessage('Primary action selected.')}><Icon name="check" size={18}/> Apply settings</CloudstormButton><CloudstormButton onClick={()=>setMessage('Secondary action selected.')}>Edit effect</CloudstormButton><CloudstormButton disabled>Unavailable</CloudstormButton></div></section>
 <section className="surface"><h2>Icon controls</h2><div className="cloudstorm-gallery-row">{[['plus','Add effect'],['refresh','Reset'],['close','Remove']].map(([icon,label])=><CloudstormButton key={label} variant="icon" aria-label={label} title={label} onClick={()=>setMessage(label+' selected.')}><Icon name={icon} size={19}/></CloudstormButton>)}<CloudstormButton aria-pressed={enabled} onClick={()=>{setEnabled(!enabled);setMessage(!enabled?'Preview enabled.':'Preview disabled.')}}>{enabled?'Enabled':'Disabled'}</CloudstormButton></div></section>
 <p role="status">{message}</p><p className="helper">Original transparent PNG surfaces; no labels or symbols baked into the artwork. Experimental, not a released app theme.</p>
 </main></div>;
}
