import React,{useEffect,useRef,useState} from 'react';
import {Icon,IconButton,Dialog,Artwork,FilePreview,Empty,Heading,nameOf,timeOf,bytesOf} from './ui.jsx';
import {mergeQueue,assignQueueImage} from './uploadQueue.js';
import TagFilter,{TagChips} from './TagFilter.jsx';
import EditAudio from './EditAudio.jsx';
import Rating from './Rating.jsx';
import {DEFAULT_FILTERS,SORTS,safeFilters,filterLibrary} from './libraryModel.js';
import {IMAGE_EXTENSIONS} from './mediaSelection.js';
const EMPTY={jobs:[],images:[],seq:0};
export default function Library({tracks,summary,theme,api,run,refresh,config,online,selected,setSelected,onPlay,onSelectTrack,onDetails,favorite,pending,visible,profileId,categoryRequest}){
 const [filters,setFilters]=useState({...DEFAULT_FILTERS}),[catalog,setCatalog]=useState(null),[tagOpen,setTagOpen]=useState(false),[tab,setTab]=useState('tracks'),[importOpen,setImportOpen]=useState(false),[profiles,setProfiles]=useState([]),[filterError,setFilterError]=useState('');
 const [filtersProfile,setFiltersProfile]=useState(null);const filterDirty=useRef(false),categorySeen=useRef(null);
 useEffect(()=>{let live=true;setFiltersProfile(null);filterDirty.current=false;api.profileDataFor(profileId).then(data=>{if(live){setFilters(safeFilters(data.preferences.library));setFiltersProfile(profileId);setFilterError('')}}).catch(e=>{if(live)setFilterError(e.message)});return()=>{live=false}},[profileId]);
 const changeFilters=next=>{filterDirty.current=true;setFilters(old=>typeof next==='function'?next(old):next)};
 useEffect(()=>{if(!filtersProfile||filtersProfile!==profileId||!filterDirty.current)return;const id=filtersProfile;const timer=setTimeout(()=>{api.saveProfilePreferences(id,{library:filters}).then(()=>setFilterError('')).catch(e=>setFilterError('Filters could not be saved: '+e.message))},650);return()=>clearTimeout(timer)},[filters,filtersProfile,profileId]);
 useEffect(()=>{if(!visible)return;let live=true;api.libraryCatalog().then(c=>{if(live)setCatalog(c)}).catch(e=>setFilterError(e.message));api.profiles().then(p=>{if(live)setProfiles(p.profiles)}).catch(()=>{});return()=>{live=false}},[visible,tracks]);
 useEffect(()=>{if(categoryRequest&&filtersProfile===profileId&&categorySeen.current!==categoryRequest.nonce){categorySeen.current=categoryRequest.nonce;changeFilters(old=>({...old,category:categoryRequest.id}));setTab('tracks')}},[categoryRequest,filtersProfile,profileId]);
 useEffect(()=>{if(!catalog||filtersProfile!==profileId)return;const ids=new Set(catalog.tags.map(t=>t.id));const include=filters.include.filter(id=>ids.has(id)),exclude=filters.exclude.filter(id=>ids.has(id));if(include.length!==filters.include.length||exclude.length!==filters.exclude.length)changeFilters({...filters,include,exclude})},[catalog,filtersProfile,profileId]);
 const reset=()=>changeFilters({...DEFAULT_FILTERS,view:filters.view});
 const search=filters.query,onlyFavorites=filters.favorites;const setSearch=query=>changeFilters(old=>({...old,query}));const setOnlyFavorites=favorites=>changeFilters(old=>({...old,favorites}));
 const [queue,setQueue]=useState(EMPTY),[working,setWorking]=useState(false),[progress,setProgress]=useState(0),[current,setCurrent]=useState(null),[error,setError]=useState('');
 const [deleting,setDeleting]=useState(null),[deletingBusy,setDeletingBusy]=useState(false),[deletingError,setDeletingError]=useState('');
 useEffect(()=>{if(!config?.allow_track_deletion)setDeleting(null)},[config?.allow_track_deletion]);
 const deleteSelected=async()=>{if(!deleting||deletingBusy||!online)return;setDeletingBusy(true);setDeletingError('');try{const result=await api.deleteTrack(deleting.id);if(selected===deleting.id)setSelected(null);setDeleting(null);setFilterError(result.warning||'');await refresh(true)}catch(e){setDeletingError(e.message)}finally{setDeletingBusy(false)}};
 const [editing,setEditing]=useState(null),[editImage,setEditImage]=useState(null),[imageSaving,setImageSaving]=useState(false),[imageError,setImageError]=useState('');
 const [actionTrack,setActionTrack]=useState(null);
 const held=useRef({timer:null,suppress:false,x:0,y:0});
 const cancelHold=()=>{clearTimeout(held.current.timer);held.current.timer=null;};
 const beginHold=(e,track)=>{
  if(e.pointerType==='mouse'&&e.button!==0)return;
  cancelHold();held.current.suppress=false;held.current.x=e.clientX;held.current.y=e.clientY;
  held.current.timer=setTimeout(()=>{held.current.timer=null;held.current.suppress=true;setActionTrack(track)},550);
 };
 const moveHold=e=>{if(Math.abs(e.clientX-held.current.x)>12||Math.abs(e.clientY-held.current.y)>12)cancelHold();};
 useEffect(()=>()=>clearTimeout(held.current.timer),[]);
 const selectRow=(e,track)=>{
  if(held.current.suppress){held.current.suppress=false;return;}
  if(online&&!pending.has('playback'))onSelectTrack(track);
 };
 const action=callback=>{const track=actionTrack;setActionTrack(null);callback(track)};
 const input=useRef(null),imageInput=useRef(null),stop=useRef(false),jobAbort=useRef(null);
 useEffect(()=>{const warn=e=>{if(working){e.preventDefault();e.returnValue='';}};addEventListener('beforeunload',warn);return()=>removeEventListener('beforeunload',warn)},[working]);
 const favorites=tracks.filter(t=>t.favorite),filtered=filterLibrary(tracks,filters);
 const pick=e=>{const files=Array.from(e.target.files||[]);e.target.value='';if(!files.length)return;try{const next=mergeQueue(queue,files,config?.formats||[]);if(next.jobs.some(j=>j.file.size>(config?.max_upload_bytes||5368709120)))throw new Error('An audio file exceeds the '+bytesOf(config?.max_upload_bytes||5368709120)+' limit.');next.jobs=next.jobs.map(j=>({...j,uploadKey:j.uploadKey||Array.from(crypto.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,'0')).join('')}));setQueue(next);setError('');}catch(err){setError(err.message)}};
 const update=(id,values)=>setQueue(old=>({...old,jobs:old.jobs.map(j=>j.id===id?{...j,...values}:j)}));
 const assign=(id,imageId)=>{try{setQueue(assignQueueImage(queue,id,imageId));setError('');}catch(err){setError(err.message)}};
 const upload=async()=>{if(working||!online)return;stop.current=false;setWorking(true);setError('');
  for(const entry of queue.jobs.filter(j=>j.status!=='done')){
   if(stop.current)break;let audioId=entry.uploadedId;
   try{setCurrent(entry.id);setProgress(0);
    if(!audioId){update(entry.id,{status:'Uploading audio',error:''});const job=api.uploadWithProgress(entry.file,setProgress,entry.uploadKey);jobAbort.current=job.abort;const result=await job.promise;audioId=result.id;update(entry.id,{uploadedId:audioId,status:'Audio saved'});}
    const image=queue.images.find(i=>i.id===entry.imageId);
    if(stop.current){update(entry.id,{uploadedId:audioId,status:'Paused',error:''});break;}
    if(image){update(entry.id,{status:'Saving thumbnail'});setProgress(0);const job=api.uploadThumbnailWithProgress(audioId,image.file,setProgress);jobAbort.current=job.abort;await job.promise;}
    update(entry.id,{uploadedId:audioId,status:'done',error:''});
   }catch(err){update(entry.id,{uploadedId:audioId,status:'error',error:err.message});if(/connection|network|cancel/i.test(err.message)){stop.current=true;setError('Queue paused. Completed audio files are safe; retry the remaining files when ready.');}}
   finally{jobAbort.current=null;}
  }
  setWorking(false);setCurrent(null);setProgress(0);await refresh(true);
 };
 const edit=track=>{setEditing(track);};
 const openImport=()=>{setImportOpen(true);setError('');};
 return <section className="library-page" hidden={!visible}>
 <Heading eyebrow="ON YOUR PI" title="Library" action={<button className="primary compact" onClick={openImport}><Icon name={working?'upload':'plus'} size={17}/>{working?'Upload progress':'Add audio'}</button>}>Familiar sounds. Familiar pictures.</Heading>
 <div className="segmented library-tabs" aria-label="Library section"><button className={tab==='tracks'?'selected':''} onClick={()=>setTab('tracks')}>Tracks</button><button className={tab==='playlists'?'selected':''} onClick={()=>setTab('playlists')}>Playlists</button></div>
 {tab==='playlists'?<Empty icon="music" title="Playlists">Coming soon</Empty>:<>
 <section className="favorites-section"><header className="section-title"><h2><Icon name="heart" size={17}/> Favorites <span>{favorites.length}</span></h2><small>Saved to this profile on your Pi</small></header>
 {favorites.length?<div className="favorite-grid">{favorites.map(t=><div className="favorite-card" key={t.id}><button className="favorite-play" onClick={()=>onSelectTrack(t)} disabled={!online||pending.has('playback')} aria-label={'Select '+nameOf(t)}><Artwork src={t.artwork} theme={theme}/><span>{nameOf(t)}</span><span className="play-overlay"><Icon name="play" size={22}/></span></button><IconButton icon="heart" label={'Remove '+nameOf(t)+' from favorites'} active aria-pressed="true" disabled={!online||pending.has('favorite:'+t.id)} onClick={()=>favorite(t)}/></div>)}</div>:<div className="favorites-empty"><Icon name="heart" size={23}/><p>Tap the heart beside an audio file to save it here.</p></div>}
 </section>
 <div className="library-toolbar"><div className="segmented" aria-label="Library filter"><button className={!onlyFavorites?'selected':''} aria-pressed={!onlyFavorites} onClick={()=>setOnlyFavorites(false)}>All audio <span>{tracks.length}</span></button><button className={onlyFavorites?'selected':''} aria-pressed={onlyFavorites} onClick={()=>setOnlyFavorites(true)}><Icon name="heart" size={14}/> Favorites</button></div><label className="search-field"><Icon name="search" size={17}/><input type="search" placeholder="Find an audio file" aria-label="Search library" value={search} onChange={e=>setSearch(e.target.value)}/></label></div>
 <div className="discovery-toolbar"><label><input type="checkbox" checked={filters.descriptions} onChange={e=>changeFilters({...filters,descriptions:e.target.checked})}/> Include descriptions</label><button className="secondary compact" disabled={!catalog} onClick={()=>setTagOpen(true)}><Icon name="layers" size={16}/>Tags</button><label className="sr-only" htmlFor="library-sort">Sort audio</label><select id="library-sort" value={filters.sort} onChange={e=>changeFilters({...filters,sort:e.target.value})}>{Object.entries(SORTS).map(([id,n])=><option key={id} value={id}>{n}</option>)}</select><button className="secondary compact sort-direction" aria-label={filters.descending?'Descending, switch to ascending':'Ascending, switch to descending'} onClick={()=>changeFilters({...filters,descending:!filters.descending})}>{filters.descending?'↓':'↑'}</button><button className="text-button" onClick={reset}>Reset</button></div>
 <div className="applied-tags"><TagChips ids={filters.include} catalog={catalog} onRemove={id=>changeFilters({...filters,include:filters.include.filter(t=>t!==id)})}/><TagChips ids={filters.exclude} catalog={catalog} exclude onRemove={id=>changeFilters({...filters,exclude:filters.exclude.filter(t=>t!==id)})}/>{filters.category&&<span className="tag-chip">{catalog?.categories.find(c=>c.id===filters.category)?.name||filters.category}<button aria-label="Remove category filter" onClick={()=>changeFilters({...filters,category:''})}>×</button></span>}</div>
 <label className="ratings-profile-select">My ratings <select aria-label="View profile ratings" value={filters.ratingProfile} onChange={e=>changeFilters({...filters,ratingProfile:e.target.value})}><option value="">Current profile</option>{profiles.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
 {filterError&&<p role="alert" className="inline-warning">{filterError}</p>}
 <div className="audio-list">{filtered.map(t=><div className={'audio-row library-rated-row '+(selected===t.id?'selected':'')} key={t.id}>
  <button className="audio-select" onClick={e=>selectRow(e,t)} disabled={!online||pending.has('playback')} onPointerDown={e=>beginHold(e,t)} onPointerMove={moveHold} onPointerUp={cancelHold} onPointerCancel={cancelHold} onPointerLeave={cancelHold} onContextMenu={e=>{e.preventDefault();cancelHold();held.current.suppress=true;setActionTrack(t)}} aria-label={'Select '+nameOf(t)} aria-pressed={selected===t.id}>
   <Artwork src={t.artwork} theme={theme}/>
   <span><strong>{nameOf(t)}</strong><small>{t.duration_seconds&&<span>{timeOf(t.duration_seconds)}</span>}<span className="file-size">Size {bytesOf(t.bytes)}</span><span>{t.id.split('.').pop().toUpperCase()}</span></small><span className="library-rating">★ {t.rating==null?'Unrated':t.rating.toFixed(1)+' ('+t.rating_count+')'} · {filters.ratingProfile?profiles.find(p=>p.id===filters.ratingProfile)?.name||'Profile':'My rating'}: {(filters.ratingProfile?t.ratings?.find(r=>r.profile===filters.ratingProfile)?.rating:t.my_rating)??'—'}</span></span>
  </button>
  <div className="row-actions"><IconButton icon="more" label={'Options for '+nameOf(t)} onClick={()=>setActionTrack(t)}/></div>
  <div className="library-track-rating"><Rating value={t.my_rating} label="My rating" disabled={!online||pending.has('rating:'+t.id)} onChange={value=>run('rating:'+t.id,()=>api.rating(t.id,value))}/></div>
 </div>)}</div>
 {!filtered.length&&<Empty icon={search?'search':'music'} title={tracks.length?'No matching audio files':'Your library is ready'}>{tracks.length?<button className="text-button" onClick={reset}>Reset filters</button>:'Add an audio file and an optional thumbnail to begin.'}</Empty>}
 <div className="library-totals"><span>Library length <strong>{summary?.duration_seconds!=null?timeOf(summary.duration_seconds):'Calculating…'}</strong></span><span>Total listening time <strong>{summary?.play_time_seconds!=null?timeOf(summary.play_time_seconds):'—'}</strong></span></div>
 </>}
 <p className="library-note"><Icon name="info" size={14}/> Audio and thumbnails stay on the Pi. Nothing is uploaded until you confirm.</p>
 {importOpen&&<Dialog title="Add audio files" icon="upload" kind="import-dialog" onClose={()=>setImportOpen(false)}><p className="helper">Choose audio and images together, or select them separately. Matching filenames are paired automatically; you can change each thumbnail before upload.</p><input ref={input} type="file" multiple accept={[...(config?.formats||[]),...IMAGE_EXTENSIONS].join(',')} className="sr-only" tabIndex="-1" aria-label="Choose audio files and thumbnails" onChange={pick}/><div className="picker-buttons"><button className="secondary" disabled={working} onClick={()=>input.current?.click()}><Icon name="music" size={17}/>Choose audio</button><button className="secondary" disabled={working} onClick={()=>input.current?.click()}><Icon name="image" size={17}/>Choose images</button></div>
 {!queue.jobs.length&&<div className="import-placeholder"><Icon name="upload" size={28}/><p>Select multiple files with Shift or Ctrl on Windows.</p><small>{queue.images.length?queue.images.length+' images selected; choose audio files next.':'JPG, PNG and WebP thumbnails · up to 8 MB each'}</small></div>}
 <div className="upload-list">{queue.jobs.map((j,i)=>{const image=queue.images.find(im=>im.id===j.imageId);return <div className="upload-row" key={j.id}><FilePreview file={image?.file} theme={theme}/><div className="upload-row-copy"><strong>{i+1}. {j.file.name}</strong><small className={j.status==='error'?'error-text':''}>{j.status==='done'?'Saved on Pi':j.error||j.status} {current===j.id?progress+'%':''}</small><select aria-label={'Thumbnail for '+j.file.name} disabled={working||j.status==='done'} value={j.imageId||''} onChange={e=>assign(j.id,e.target.value)}><option value="">No thumbnail</option>{queue.images.filter(im=>im.id===j.imageId||!queue.jobs.some(other=>other.id!==j.id&&other.imageId===im.id)).map(im=><option value={im.id} key={im.id}>{im.file.name}</option>)}</select>{current===j.id&&<progress value={progress} max="100"/>}</div>{j.status==='done'?<Icon name="check" size={18}/>:<IconButton icon="close" label={'Remove '+j.file.name+' from queue'} disabled={working} onClick={()=>setQueue(q=>({...q,jobs:q.jobs.filter(x=>x.id!==j.id)}))}/>}</div>})}</div>
 {error&&<p className="inline-error" role="alert">{error}</p>}
 <div className="dialog-actions"><button className="text-button" disabled={working} onClick={()=>setQueue(EMPTY)}>Clear queue</button>{working?<button className="secondary compact" onClick={()=>{stop.current=true;jobAbort.current?.();}}>Pause queue</button>:<button className="primary compact" disabled={!online||!queue.jobs.some(j=>j.status!=='done')} onClick={upload}><Icon name="upload" size={16}/>{queue.jobs.some(j=>j.status==='error')?'Retry remaining':'Upload'} ({queue.jobs.filter(j=>j.status!=='done').length})</button>}</div><div className="dialog-foot"><Icon name="info" size={14}/><small>One file at a time. Keep the app open while uploading; a failed thumbnail can be retried without sending the audio again.</small></div></Dialog>}
 {tagOpen&&<TagFilter tracks={tracks} catalog={catalog} filters={filters} onApply={changeFilters} onClose={()=>setTagOpen(false)}/>}
 {actionTrack&&<Dialog title={nameOf(actionTrack)} icon="music" kind="library-actions-dialog" onClose={()=>setActionTrack(null)}>
  <p className="helper">Choosing another track preserves Play or Pause. Play now starts the recording.</p>
  <div className="library-action-list">
   <button disabled={!online||pending.has('playback')} onClick={()=>action(onPlay)}><Icon name="play" size={18}/> Play now</button>
   <button disabled={!online||pending.has('playback')} onClick={()=>action(onSelectTrack)}><Icon name="music" size={18}/> Select (preserve Pause)</button>
   <button disabled={!online||pending.has('favorite:'+actionTrack.id)} onClick={()=>action(favorite)}><Icon name="heart" size={18}/> {actionTrack.favorite?'Remove from favorites':'Add to favorites'}</button>
   <button onClick={()=>action(onDetails)}><Icon name="info" size={18}/> Audio details & comments</button>
   <button disabled={!online||working} onClick={()=>action(edit)}><Icon name="edit" size={18}/> Edit audio details</button>
   {config?.allow_track_deletion&&<button className="danger-action" disabled={!online||working} onClick={()=>action(setDeleting)}><Icon name="close" size={18}/> Delete recording…</button>}
  </div>
 </Dialog>}
 {deleting&&config?.allow_track_deletion&&<Dialog title="Delete recording?" icon="warning" kind="track-delete-dialog" onClose={()=>{if(!deletingBusy)setDeleting(null)}}><p>Delete <strong>{nameOf(deleting)}</strong> from this host?</p><p className="helper">Its audio and thumbnail will be removed. Saved ratings, comments, favorites and listening history are retained if you add the same file again. Stop this track and change any alarm or controller default using it first.</p>{deletingError&&<p role="alert" className="inline-error">{deletingError}</p>}<div className="dialog-actions"><button className="secondary compact" disabled={deletingBusy} onClick={()=>setDeleting(null)}>Cancel</button><button className="danger compact" disabled={deletingBusy||!online} onClick={deleteSelected}>{deletingBusy?'Deleting…':'Delete recording'}</button></div></Dialog>}
 {editing&&<EditAudio track={editing} api={api} theme={theme} onClose={()=>setEditing(null)} onSaved={()=>refresh(true)}/>}

 </section>
}
