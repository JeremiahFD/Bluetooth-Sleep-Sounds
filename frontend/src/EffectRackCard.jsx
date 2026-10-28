import React from 'react';
import {Toggle,Icon} from './ui.jsx';
import {CloudstormButton} from './CloudstormButton.jsx';
export default function EffectRackCard({id,title,active,enabled,expanded,disabled,onToggle,onExpand,onRemove,onMoveUp,onMoveDown,onDrop,children}){
 return <section className="rack-card studio-glass" onDragOver={e=>e.preventDefault()} onDrop={e=>{e.preventDefault();!disabled&&onDrop?.(e.dataTransfer.getData('text/sleep-effect'))}}>
  <header className="rack-card-heading">
   {onMoveUp&&<CloudstormButton variant="icon" className="rack-drag" draggable={!disabled} disabled={disabled} aria-label={'Drag '+title+' to reorder'} onDragStart={e=>e.dataTransfer.setData('text/sleep-effect',id)}>⠿</CloudstormButton>}
   <div className="rack-card-name"><h2>{title}</h2><small><i className={'rack-light'+(active?' active':'')} aria-hidden="true"/>{active?'Enabled':enabled?'Bypassed':'Disabled'}</small></div>
   <Toggle label={'Enable '+title.toLowerCase()} checked={enabled} disabled={disabled} onChange={onToggle}/>
   <CloudstormButton aria-expanded={expanded} aria-controls={'rack-'+id} onClick={onExpand}>{expanded?'Close':'Edit +'}</CloudstormButton>
   {onRemove&&<CloudstormButton variant="icon" className="rack-remove" disabled={disabled} aria-label={'Remove '+title} onClick={onRemove}><Icon name="close" size={17}/></CloudstormButton>}
  </header>
  {onMoveUp&&<div className="rack-order-actions"><CloudstormButton variant="icon" disabled={disabled} onClick={onMoveUp} aria-label={'Move '+title+' up'}><span className="cloud-arrow-up"><Icon name="right" size={17}/></span></CloudstormButton><CloudstormButton variant="icon" disabled={disabled} onClick={onMoveDown} aria-label={'Move '+title+' down'}><span className="cloud-arrow-down"><Icon name="right" size={17}/></span></CloudstormButton></div>}
  {expanded&&<div id={'rack-'+id} className="rack-card-content">{children}</div>}
 </section>;
}
