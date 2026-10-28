/** One in-flight update, field-level intent, and authoritative acknowledgements.
 * A later edit must never be cleared by an earlier response or stale polling. */
export const audioValues = config => ({...config?.audio_processing, normalization:!!config?.normalization});
export class LiveAudioEditor {
 constructor({config={},save,delay=300,onChange=()=>{},onSaved=()=>{}}){
  this.base=audioValues(config);this.revision=config?.audio_processing_revision??0;
  this.pending=new Map();this.sequence=0;this.save=save;this.delay=delay;
  this.onChange=onChange;this.onSaved=onSaved;this.enabled=true;this.saving=false;this.error='';this.saved=false;
  this.timer=null;this.flight=null;this.disposed=false;
 }
 snapshot(){return {draft:{...this.base,...Object.fromEntries([...this.pending].map(([k,v])=>[k,v.value]))},dirty:this.pending.size>0,saving:this.saving,error:this.error,saved:this.saved};}
 emit(){if(!this.disposed)this.onChange(this.snapshot());}
 receive(config){
  const revision=config?.audio_processing_revision??0;
  // Equal revisions can carry normalization changes on older servers. Never let
  // polling racing a write overwrite its acknowledged result.
  if(!this.saving&&revision>=this.revision){this.base=audioValues(config);this.revision=revision;this.emit();}
 }
 setEnabled(enabled){this.enabled=enabled;if(enabled&&this.pending.size&&!this.error)this.schedule();}
 edit(patch){
  for(const [key,value] of Object.entries(patch))this.pending.set(key,{value,version:++this.sequence});
  this.error='';this.saved=false;this.emit();this.schedule();
 }
 schedule(){clearTimeout(this.timer);if(this.enabled&&!this.disposed)this.timer=setTimeout(()=>{this.flush();},this.delay);}
 async flush(){
  clearTimeout(this.timer);
  if(this.flight){await this.flight;return this.error?false:this.flush();}
  if(!this.enabled)return false;
  if(!this.pending.size)return true;
  const sent=new Map(this.pending),patch=Object.fromEntries([...sent].map(([k,v])=>[k,v.value]));
  this.saving=true;this.error='';this.emit();
  this.flight=(async()=>{
   try{
    const actual=await this.save(patch);
    this.base=audioValues(actual);this.revision=actual.audio_processing_revision??actual.revision??this.revision;
    for(const [key,intent] of sent)if(this.pending.get(key)?.version===intent.version)this.pending.delete(key);
    this.saved=!this.pending.size;
    // Refresh failures must not relabel a successful persisted update as failed.
    Promise.resolve().then(()=>this.onSaved()).catch(()=>{});
   }catch(error){this.error=error.message||'Audio settings could not be saved.';this.saved=false;}
   finally{this.saving=false;this.flight=null;this.emit();}
  })();
  await this.flight;
  // Drain the latest intent once, without parallel writes or endlessly retrying errors.
  if(!this.error&&this.pending.size)return this.flush();
  return !this.error;
 }
 discard(config){clearTimeout(this.timer);this.pending.clear();this.error='';this.saved=false;this.receive(config);}
 dispose(){clearTimeout(this.timer);this.onChange=()=>{};if(this.enabled&&!this.error)this.flush();this.disposed=true;}
}
