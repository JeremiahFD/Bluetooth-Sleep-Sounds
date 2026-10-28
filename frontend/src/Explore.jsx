import React,{useEffect,useState} from 'react';
import {Heading,Icon} from './ui.jsx';
export default function Explore({api,tracks,visible,onCategory}){
 const [catalog,setCatalog]=useState(null),[error,setError]=useState('');useEffect(()=>{if(visible)api.libraryCatalog().then(setCatalog).catch(e=>setError(e.message))},[visible]);
 return <section hidden={!visible} className="explore-page"><Heading eyebrow="FIND YOUR QUIET" title="Explore">A sound for every kind of night.</Heading>{error&&<p className="inline-error">{error}</p>}<div className="explore-grid">{catalog?.categories.map(c=><button className={'explore-category category-'+c.id} key={c.id} onClick={()=>onCategory(c.id)}><img src={'/ui/categories/'+(c.picture||(['weather','nature','water','noise','home','travel','music','tones'].includes(c.id)?c.id:'nature'))+'.svg'} alt=""/><span><strong>{c.name}</strong><small>{tracks.filter(t=>t.metadata?.categories?.includes(c.id)).length} audio files</small></span></button>)}</div></section>
}
