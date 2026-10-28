import {CloudstormButton} from './CloudstormButton.jsx';
import React,{useEffect,useRef,useState} from 'react';
import {Dialog,Icon,Toggle} from './ui.jsx';
import {Knob,Slider,EffectHeading,EqGraph,PrecisionDialog,StudioIcon} from './AudioStudioControls.jsx';
import {visibleBands,normalizedDraft,needsLevelWarning,newPresetId} from './audioStudioModel.js';
import {AUDIO_HELP} from './audioHelp.js';
import GainMeter from './GainMeter.jsx';
import useLiveAudio from './useLiveAudio.js';
import NoiseLayers from './NoiseLayers.jsx';
import EffectRackCard from './EffectRackCard.jsx';
import {EFFECTS,rackOrder,moveEffect,effectEnabled} from './effectRack.js';

const manualSettingsEqual=(a,b)=>!!a&&!!b&&Object.keys(a).filter(k=>!k.startsWith('normalization_')).every(k=>JSON.stringify(a[k])===JSON.stringify(b[k]));

function EffectsProcessing({config,status,api,refresh,online,onClose,navigationGuard,gainMeterEnabled=false}){
 const mounted=useRef(true);
 const alarm=status?.mode==='alarm';
 const {draft:liveDraft,saving,error,saved,dirty,edit:change,commit,reload}=useLiveAudio({config,api,refresh,enabled:online&&!alarm});
 const draft={...liveDraft};delete draft.normalization;
 const boostAccepted=useRef(false),[warning,setWarning]=useState(null);
 const changeSafe=patch=>{if(!boostAccepted.current&&needsLevelWarning({...draft,...patch},draft)){setWarning(patch);return;}change(patch);};
 const [precision,setPrecision]=useState(null),[help,setHelp]=useState(null),[chosenId,setChosenId]=useState('flat');
 const [presets,setPresets]=useState({builtin:[],custom:[],revision:0}),[presetError,setPresetError]=useState(''),[presetBusy,setPresetBusy]=useState(false);
 const [presetDialog,setPresetDialog]=useState(null),[presetName,setPresetName]=useState(''),[dialogError,setDialogError]=useState(''),[manage,setManage]=useState(false);
 const [editing,setEditing]=useState({});
 const order=rackOrder(draft.rack_order),rackSupported=!!config?.audio_rack_supported;
 const move=(id,direction)=>{const i=order.indexOf(id),to=i+direction;if(to>=0&&to<order.length){const next=[...order];[next[i],next[to]]=[next[to],next[i]];change({rack_order:next});}};
 const remove=id=>change({rack_order:order.filter(v=>v!==id),[id+'_enabled']:false});
 const ranges=config?.audio_processing_ranges||{},available=!!config?.audio_processing;
 const disabled=presetBusy||!online||alarm;
 const all=[...presets.builtin,...presets.custom],chosen=all.find(p=>p.id===chosenId);
 const matching=chosen&&manualSettingsEqual(chosen.settings,draft)?chosen:all.find(p=>manualSettingsEqual(p.settings,draft));
 useEffect(()=>{mounted.current=true;window.scrollTo({top:0,behavior:"instant"});return()=>{mounted.current=false}},[]);
 const loadPresets=async()=>{try{const result=await api.audioPresets();if(mounted.current){setPresets(result);setPresetError(result.error||'');return result;}}catch(e){if(mounted.current)setPresetError(e.message||'Could not load presets.');}return null;};
 useEffect(()=>{if(online&&config?.audio_presets_supported)loadPresets();},[online,config?.audio_presets_revision]);
 const permitClose=()=>{if(presetBusy)return false;if(saving||dirty&&!error){commit();return false;}return !dirty||window.confirm('Discard audio changes that could not be saved?');};
 useEffect(()=>{if(navigationGuard)navigationGuard.current=permitClose;return()=>{if(navigationGuard)navigationGuard.current=null}},[dirty,saving,presetBusy,error]);
 const close=()=>{if(permitClose())onClose();};
 const edit=(key,value)=>changeSafe({[key]:value});
 const resetKeys=keys=>{if(disabled)return;change(Object.fromEntries(keys.map(key=>[key,config.audio_processing_defaults[key]])));};
 const toggleEdit=key=>setEditing(old=>({...old,[key]:!old[key]}));
 const select=p=>{if(disabled)return;const settings={...config.audio_processing_defaults,...p.settings};delete settings.normalization_strength;delete settings.normalization_ceiling_db;changeSafe(settings);setChosenId(p.id);};
 const reset=()=>{if(!disabled){const settings={...config.audio_processing_defaults};delete settings.normalization_strength;delete settings.normalization_ceiling_db;change(settings);setChosenId('flat');}};
 const openPreset=(action,preset=null)=>{
  if(presetBusy||!online)return;
  setPresetDialog({action,id:preset?.id||newPresetId(),original:preset?.name||''});setPresetName(preset?.name||'');setDialogError('');
 };
 const mutatePreset=async e=>{
  e?.preventDefault();if(presetBusy||!presetDialog||!online)return;
  const d=presetDialog,payload={action:d.action,id:d.id,expected_revision:presets.revision};
  try{
   if(['create','rename'].includes(d.action)){if(!presetName.trim()||presetName.trim().length>64)throw new Error('Enter a name with 1 to 64 characters.');payload.name=presetName.trim();}
   if(['create','update'].includes(d.action))payload.settings=normalizedDraft(draft,ranges);
   setPresetBusy(true);setDialogError('');
   const result=await api.saveAudioPreset(payload);setPresets(result);setPresetError(result.error||'');
   if(d.action!=='delete')setChosenId(d.id);
   setPresetDialog(null);setDialogError('');
  }catch(e){setDialogError(e.message||'Preset could not be saved.');}finally{setPresetBusy(false);}
 };
 const onPresetSelect=e=>{const id=e.target.value;if(id==='__new__')openPreset('create');else if(id==='__manage__')setManage(true);else{const p=all.find(p=>p.id===id);if(p)select(p);}};
 const slider=(name,label,unit,step=1,log=false,off=false)=><Slider key={name} {...{name,label,unit,step,log}} value={draft[name]} range={ranges[name]||[0,100]} onChange={edit} onPrecision={setPrecision} resetValue={config.audio_processing_defaults[name]} disabled={disabled||off}/>;
 const info=help&&AUDIO_HELP[help];
 return <section className="audio-studio" aria-labelledby="audio-studio-title">
 <header className="studio-header"><button className="studio-back" aria-label="Back to app" onClick={close}><Icon name="right" size={25}/></button><div><h1 id="audio-studio-title">Audio Processing</h1></div><button className="studio-reset" disabled={disabled} onClick={reset}><Icon name="refresh" size={19}/><span>Reset</span></button></header>
 {/SleepSoundsAndroid\//.test(navigator.userAgent)&&<a className="secondary compact" href="sleep-sounds://connections" onClick={e=>{if(!permitClose())e.preventDefault()}}>Host connections &amp; discovery</a>}
 {!available?<p className="inline-warning">This Pi build does not support the new audio controls yet.</p>:<>
 <section className="studio-presets studio-glass" aria-label="Audio presets"><div className="studio-presets-heading"><span>PRESETS</span><small>Starting points. Fine-tune for your recordings.</small></div>
 <div className="studio-preset-cards">{presets.builtin.slice(0,6).map(p=><button key={p.id} type="button" className={'studio-preset-card'+(matching?.id===p.id?' selected':'')} aria-pressed={matching?.id===p.id} disabled={disabled} onClick={()=>select(p)}><StudioIcon name={p.icon} size={30}/><strong>{p.name}</strong><small>{p.description}</small></button>)}</div>
 <div className="studio-preset-toolbar"><div className="studio-preset-select-wrap"><label className="sr-only" htmlFor="audio-preset-select">Choose an audio preset</label><select id="audio-preset-select" aria-label="Choose an audio preset" value={matching?.id||''} onChange={onPresetSelect} disabled={disabled||!config.audio_presets_supported}><option value="">Custom / unsaved settings</option><optgroup label="Starting presets">{presets.builtin.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</optgroup>{presets.custom.length>0&&<optgroup label="My presets · saved on Pi">{presets.custom.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</optgroup>}<option value="__new__">＋ Add new preset…</option><option value="__manage__">Manage my presets…</option></select></div>
 <button className="studio-inline-button" disabled={disabled||!!presets.error||!config.audio_presets_supported} onClick={()=>openPreset('create')}><Icon name="plus" size={16}/> Save as preset</button><button className="studio-info" aria-label="About selected preset" onClick={()=>setHelp('Preset')}><Icon name="info" size={19}/></button></div>
 {presetError&&<p className="inline-warning" role="status">{presetError} <button className="text-button" onClick={loadPresets}>Reload presets</button></p>}
 </section>
 {draft.bypass&&<p className="studio-banner">Manual processing is bypassed. Your gain, EQ and dynamics settings are retained.</p>}
 {alarm&&<p className="studio-banner">Dismiss the alarm before adjusting audio. Alarms bypass these effects.</p>}
 {!online&&<p className="studio-banner">Reconnect to the Pi before applying or saving settings.</p>}
 <div className="rack-toolbar"><CloudstormButton onClick={()=>setEditing(Object.fromEntries([...order,'normalization'].map(id=>[id,true])))}>Expand all</CloudstormButton><CloudstormButton onClick={()=>setEditing({})}>Collapse all</CloudstormButton><label>Add effect <select aria-label="Add effect" value="" disabled={disabled||!rackSupported} onChange={e=>{const id=e.target.value;if(id){changeSafe({rack_order:[...order,id],[id+'_enabled']:true,bypass:false});setEditing(old=>({...old,[id]:true}));}}}><option value="">Choose effect</option>{Object.entries(EFFECTS).filter(([id])=>!order.includes(id)).map(([id,title])=><option key={id} value={id}>{title}</option>)}</select></label></div>
 {!rackSupported&&<p className="studio-banner">Update the host backend to use effect ordering, Echo and noise layers.</p>}
 <div className="effects-rack" aria-label="Effects in processing order">
 {order.map(id=><EffectRackCard key={id} id={id} title={EFFECTS[id]} enabled={effectEnabled(id,draft)} active={effectEnabled(id,draft)&&!draft.bypass&&!liveDraft.normalization} expanded={!!editing[id]} disabled={disabled} onToggle={v=>changeSafe({[id+'_enabled']:v,...(v?{bypass:false}:{})})} onExpand={()=>toggleEdit(id)} onRemove={rackSupported?()=>remove(id):null} onMoveUp={rackSupported?()=>move(id,-1):null} onMoveDown={()=>move(id,1)} onDrop={from=>rackSupported&&order.includes(from)&&change({rack_order:moveEffect(order,from,id)})}>
{id==='gain'&&<>
 <div className="studio-gain-slider"><div><label htmlFor="studio-gain-range">Gain</label><button type="button" className="studio-gain-number" aria-label="Edit Gain value" disabled={disabled} onClick={()=>setPrecision({name:'gain_db',label:'Gain',unit:'dB'})}>{draft.gain_db>0?'+':''}{draft.gain_db} dB</button></div><input id="studio-gain-range" type="range" min={ranges.gain_db?.[0]??-12} max={ranges.gain_db?.[1]??18} step="0.5" value={draft.gain_db} disabled={disabled} aria-label="Gain" onChange={e=>edit('gain_db',Number(e.target.value))}/><div className="studio-range-ends"><span>{ranges.gain_db?.[0]??-12} dB</span><span>{ranges.gain_db?.[1]??18} dB</span></div></div>
 <GainMeter api={api} online={online} status={status} dirty={dirty} enabled={gainMeterEnabled&&!draft.bypass&&!liveDraft.normalization&&effectEnabled('gain',draft)}/><p className="studio-gain-note"><Icon name="info" size={14}/> Boosting can distort loud sections.</p></>}{id==='eq'&&<>
 <div className="studio-band-selector" role="group" aria-label="Equalizer band count">{[3,5].map(n=><button key={n} type="button" aria-pressed={draft.eq_bands===n} className={draft.eq_bands===n?'selected':''} onClick={()=>edit('eq_bands',n)} disabled={disabled||(n===5&&!config.audio_processing_eq_modes?.includes(5))}>{n}-band</button>)}</div>
 <EqGraph settings={draft}/>
 <div className={'studio-band-knobs bands-'+draft.eq_bands}>{visibleBands(draft.eq_bands).map(b=><div key={b.key} className="studio-band"><strong>{draft.eq_bands===3?b.simple:b.label}</strong>{draft.eq_bands===3&&<small>{b.label}</small>}<Knob name={b.key} label={(draft.eq_bands===3?b.simple+' · ':'')+b.label} value={draft[b.key]} min={-12} max={12} onChange={edit} onPrecision={setPrecision} disabled={disabled}/></div>)}</div>
 </>}{id==='limiter'&&<>
 <button className="studio-tip" onClick={()=>setHelp('Limiter')}><Icon name="info" size={19}/><span>Try a −2 dBFS ceiling. Start quietly and listen to the loudest sections.</span></button>
 <div className="studio-parameter-well">{slider('limiter_ceiling_db','Output ceiling','dBFS',.1,false)}<div className="studio-pair">{slider('limiter_attack_ms','Attack / lookahead','ms',.1,true)}{slider('limiter_release_ms','Release','ms',1,true)}</div></div>
 </>}{id==='compressor'&&<>
 <button className="studio-tip" onClick={()=>setHelp('Compressor')}><Icon name="info" size={19}/><span>Start gently at 2:1. Lower threshold until loud sections sound controlled.</span></button>
 <div className="studio-parameter-well">{slider('compressor_threshold_db','Threshold','dBFS',.1,false)}{slider('compressor_ratio','Ratio',':1',.1,true)}<div className="studio-pair">{slider('compressor_attack_ms','Attack','ms',.1,true)}{slider('compressor_release_ms','Release','ms',1,true)}</div>{slider('compressor_makeup_db','Makeup gain','dB',.1,false)}</div>
 </>}
 {id==='echo'&&<div className="studio-parameter-well"><p>One delayed reflection with level compensation. This is echo, not convolution reverb.</p>{slider('echo_delay_ms','Delay','ms',1)}{slider('echo_decay','Reflection level','',.01)}</div>}
 <button type="button" className="secondary compact" disabled={disabled} onClick={()=>resetKeys(Object.keys(config.audio_processing_defaults).filter(key=>key.startsWith(id+'_')&&key!==id+'_enabled'))}>Reset {EFFECTS[id]}</button>
 </EffectRackCard>)}
 </div>
 <NoiseLayers draft={{...draft,normalization:!!liveDraft.normalization}} change={patch=>change({...patch,...(!liveDraft.normalization&&(patch.noise1_enabled===true||patch.noise2_enabled===true)?{bypass:false}:{})})} disabled={disabled} supported={rackSupported}/>
 <EffectRackCard id="normalization" title="Normalization" enabled={!!liveDraft.normalization} active={!!liveDraft.normalization} expanded={!!editing.normalization} disabled={disabled} onToggle={v=>change({normalization:v})} onExpand={()=>toggleEdit('normalization')}>
 <p>Normalization currently takes over from the manual rack. Your manual chain is retained.</p><label>Leveling preset <select value={draft.normalization_strength||'balanced'} disabled={disabled} onChange={e=>change({normalization_strength:e.target.value,normalization:!!liveDraft.normalization})}>{['light','balanced','night'].map(v=><option key={v} value={v}>{v}</option>)}</select></label>{slider('normalization_ceiling_db','Output ceiling','dBFS',.1)}
 </EffectRackCard>
 <div className="studio-signal-note">The order above is the actual manual processing order. A limiter only protects stages before it. Normalization is a separate mode on this page. Live visuals stay opt-in.</div>
 {error&&<p className="studio-banner error" role="alert">{error} <button className="text-button" onClick={()=>commit()}>Retry</button> <button className="text-button" onClick={reload}>Reload saved settings</button></p>}
 <div className="studio-apply-bar"><div className="studio-all-bypass"><Toggle label="Bypass all processing" checked={draft.bypass&&!liveDraft.normalization} disabled={disabled} onChange={v=>change({bypass:v,normalization:v?false:!!liveDraft.normalization})}/><label>Bypass all</label></div><div className="studio-apply-status" role="status">{saving?'Applying to Pi…':saved?'Applied and saved on Pi':dirty?'Changes pending…':'Saved settings'}<small>{saving||dirty?'Changes apply automatically. Keep editing while they save.':'Changes apply automatically. Original recordings are unchanged.'}</small></div><CloudstormButton variant="primary" className="studio-apply-button" disabled={disabled||saving||!dirty} onClick={()=>commit()}><Icon name="check" size={18}/>{saving?'Applying…':'Apply settings'}</CloudstormButton></div>
 </>}
 {precision&&<PrecisionDialog control={precision} value={draft[precision.name]} range={ranges[precision.name]} onSet={edit} onClose={()=>setPrecision(null)}/>}
 {warning&&<Dialog title="Enable live level adjustments?" icon="warning" onClose={()=>setWarning(null)}><p>Boosting gain, EQ or makeup gain can distort loud sections. Turn playback volume down before adjusting. Further changes on this page will apply automatically.</p><div className="dialog-actions"><button className="secondary" onClick={()=>setWarning(null)}>Cancel</button><button className="primary" onClick={()=>{boostAccepted.current=true;change(warning);setWarning(null)}}>Apply changes</button></div></Dialog>}
 {help&&<Dialog title={help==='Preset'?'About this preset':'About '+help} icon="info" kind="studio-help-dialog" onClose={()=>setHelp(null)}>{help==='Preset'?<><h3>{matching?.name||'Custom settings'}</h3><p>{matching?.description||'Your current combination of audio controls.'}</p><p className="studio-source-label">{matching?.source?.label||(matching?.kind==='custom'?'Your named preset · saved on Pi':'Unsaved app settings')}</p><p>{matching?.source?.note||'Presets include gain, EQ mode and bands, dynamics and bypass. They do not change hardware volume, playback volume, normalization, alarms or tracks.'}</p><p className="helper">Starting points are not auditioned on your speakers. Save your own tuned version with Add new preset.</p>{matching?.source?.url&&<a className="studio-source-link" href={matching.source.url} target="_blank" rel="noreferrer">Read the source documentation ↗</a>}</>:<><p>{info.intro}</p><ol className="studio-help-steps">{info.steps.map((step,i)=><li key={i}>{step}</li>)}</ol><a className="studio-source-link" href={info.url} target="_blank" rel="noreferrer">{info.source} ↗</a></>}</Dialog>}

 {manage&&<Dialog title="My audio presets" icon="sliders" kind="studio-manage-dialog" onClose={()=>!presetBusy&&setManage(false)}><p className="helper">Saved on the Pi and available to your other devices. Built-in starting presets stay unchanged.</p>{presets.custom.length===0?<p>No custom presets yet.</p>:<div className="studio-managed-list">{presets.custom.map(p=><article key={p.id}><strong>{p.name}</strong><div><button onClick={()=>{select(p);setManage(false)}}>Load</button><button onClick={()=>openPreset('rename',p)}>Rename</button><button onClick={()=>openPreset('update',p)}>Replace with current</button><button className="danger" onClick={()=>openPreset('delete',p)}>Delete</button></div></article>)}</div>}<button className="primary" disabled={presetBusy||!online||!!presets.error} onClick={()=>openPreset('create')}><Icon name="plus" size={17}/> Add new preset</button></Dialog>}
 {presetDialog&&<Dialog title={{create:'Add new preset',rename:'Rename preset',update:'Replace preset settings?',delete:'Delete preset?'}[presetDialog.action]} icon="sliders" kind="studio-preset-dialog" onClose={()=>!presetBusy&&setPresetDialog(null)}><form onSubmit={mutatePreset}>{['create','rename'].includes(presetDialog.action)?<label className="field-label">Preset name<input autoFocus aria-label="Preset name" value={presetName} maxLength={64} disabled={presetBusy} onChange={e=>setPresetName(e.target.value)} placeholder="e.g. Rain at bedtime" required/></label>:<p>{presetDialog.action==='delete'?'Remove “'+presetDialog.original+'” from your saved presets? Your current audio and recordings will not change.':'Replace the settings in “'+presetDialog.original+'” with the controls currently shown? The old preset values will be replaced.'}</p>}<p className="helper">{presetDialog.action==='create'?'Saves the displayed gain, EQ and dynamics on the Pi. Saving does not apply them to playback.':'Your recordings remain unchanged.'}</p>{dialogError&&<p className="inline-error" role="alert">{dialogError} <button type="button" className="text-button" onClick={async()=>{await loadPresets();setDialogError('Preset list reloaded. Review the name and try again.')}}>Reload preset list</button></p>}<div className="dialog-actions"><button type="button" className="secondary" disabled={presetBusy} onClick={()=>setPresetDialog(null)}>Cancel</button><button type="submit" className="primary" disabled={presetBusy||!online}>{presetBusy?'Saving…':presetDialog.action==='delete'?'Delete preset':presetDialog.action==='update'?'Replace settings':'Save preset'}</button></div></form></Dialog>}
 </section>;
}

export default function AudioProcessing(props){
 return <EffectsProcessing {...props}/>;
}
