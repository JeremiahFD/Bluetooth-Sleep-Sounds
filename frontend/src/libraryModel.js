/** Shared search grammar: Unicode word-aware exclusions, quoted phrases, no regex input. */
export function searchTerms(query='') {
 const result=[];let i=0;
 while(i<query.length){while(/\s/.test(query[i]||'')&&i<query.length)i++;if(i>=query.length)break;
 let exclude=false;if(query[i]==='-'&&i+1<query.length&&!/\s/.test(query[i+1])){exclude=true;i++;}
 let value='';if(query[i]==='"'){i++;while(i<query.length&&query[i]!=='"')value+=query[i++];if(query[i]==='"')i++;}
 else while(i<query.length&&!/\s/.test(query[i]))value+=query[i++];
 if(value)result.push({value:value.normalize('NFKC').toLocaleLowerCase().replace(/\s+/g,' '),exclude});
 }return result;
}
export function matchesSearch(track,query,descriptions=false){
 const info=track.metadata||{};
 const corpus=[track.name,track.id,...(descriptions?[info.description,info.creator,info.attribution]:[])].filter(Boolean).join(' ').normalize('NFKC').toLocaleLowerCase().replace(/\s+/g,' ');
 const word=c=>!!c&&/[\p{L}\p{N}_]/u.test(c);
 return searchTerms(query).every(({value,exclude})=>{if(!exclude)return corpus.includes(value);
 let pos=-1;while((pos=corpus.indexOf(value,pos+1))!==-1){if((!word(value[0])||!word(corpus[pos-1]))&&(!word(value.at(-1))||!word(corpus[pos+value.length])))return false;}return true;});
}
export const DEFAULT_FILTERS={query:'',descriptions:false,include:[],exclude:[],category:'',favorites:false,sort:'added',descending:true,view:'tiles',ratingProfile:''};
export const SORTS={recent:'Recently played',name:'Name',added:'Date added',quality:'Quality',rating:'Rating',mine:'My rating',length:'Length'};
export function safeFilters(value){const base={...DEFAULT_FILTERS,...(value&&typeof value==='object'?value:{})};return {...base,
 query:typeof base.query==='string'?base.query:'',descriptions:base.descriptions===true,descending:base.descending!==false,
 favorites:base.favorites===true,include:Array.isArray(base.include)?base.include.filter(x=>typeof x==='string'):[],
 exclude:Array.isArray(base.exclude)?base.exclude.filter(x=>typeof x==='string'):[],
 sort:base.sort in SORTS?base.sort:'added',view:['tiles','grouped','compact'].includes(base.view)?base.view:'tiles'};}
export function quality(t){
 if(!t.codec)return null;
 const lossless=['flac','alac','wavpack','ape'].includes(t.codec)||t.codec.startsWith('pcm_');
 return [lossless?1:0,t.sample_rate_hz??0,t.bit_depth_bits??0,t.bitrate_kbps??0];
}
export function filterLibrary(tracks,filters){const f=safeFilters(filters);
 const rows=tracks.filter(t=>{const tags=t.metadata?.tags||[];return (!f.favorites||t.favorite)&&(!f.category||t.metadata?.categories?.includes(f.category))&&f.include.every(id=>tags.includes(id))&&!f.exclude.some(id=>tags.includes(id))&&matchesSearch(t,f.query,f.descriptions)});
 const mine=t=>f.ratingProfile?t.ratings?.find(r=>r.profile===f.ratingProfile)?.rating:t.my_rating;
 const key=t=>({recent:t.last_played_at,name:t.name,added:t.metadata?.added_at,quality:quality(t),rating:t.rating,mine:mine(t),length:t.duration_seconds})[f.sort];
 const compare=(a,b)=>Array.isArray(a)?a.reduce((v,n,i)=>v||n-b[i],0):typeof a==='string'?a.localeCompare(b,undefined,{numeric:true,sensitivity:'base'}):a-b;
 return rows.sort((a,b)=>{const av=key(a),bv=key(b);if(av==null&&bv!=null)return 1;if(bv==null&&av!=null)return -1;return (av!=null&&bv!=null?compare(av,bv)*(f.descending?-1:1):0)||String(a.name).localeCompare(String(b.name))||a.id.localeCompare(b.id)});
}
export function usedTags(tracks,catalog){const ids=new Set(tracks.flatMap(t=>t.metadata?.tags||[]));return (catalog?.tags||[]).filter(t=>ids.has(t.id));}
