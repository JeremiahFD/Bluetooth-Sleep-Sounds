import React,{useEffect,useRef,useState} from 'react';

export default function TrackComments({track,api,online=true}){
 const [posts,setPosts]=useState([]),[body,setBody]=useState(''),[reply,setReply]=useState(null),[author,setAuthor]=useState(''),[loading,setLoading]=useState(true),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const live=useRef(false),input=useRef(null);
 useEffect(()=>{live.current=true;Promise.all([api.trackComments(track),api.profileData()]).then(([discussion,profile])=>{if(live.current){setPosts(discussion.posts);setAuthor(profile.name)}}).catch(e=>{if(live.current)setError(e.message)}).finally(()=>{if(live.current)setLoading(false)});return()=>{live.current=false}},[track,api]);
 const submit=async e=>{e.preventDefault();if(busy||!online)return;setBusy(true);setError('');try{const result=await api.postTrackComment(track,body,reply?.id||null);if(live.current){setPosts(result.posts);setBody('');setReply(null)}}catch(e){if(live.current)setError(e.message)}finally{if(live.current)setBusy(false)}};
 return <section className="track-comments" aria-label="Track discussion"><h3>Comments</h3>
 {loading&&<p role="status" className="helper">Loading discussion…</p>}
 {error&&<p role="alert" className="inline-error">{error}</p>}
 {!loading&&!posts.length&&<p className="helper">No comments yet.</p>}
 {posts.map(p=><article className="feedback-post track-comment" key={p.id}><header><strong>{p.name}</strong><small>{new Date(p.created_at*1000).toLocaleString()}</small></header><p>{p.body}</p><button type="button" className="text-button" disabled={!online||busy} onClick={()=>{setReply(p);input.current?.focus()}}>Reply</button>{p.replies.map(r=><div className="feedback-reply" key={r.id}><strong>{r.name}</strong><small> · {new Date(r.created_at*1000).toLocaleString()}</small><p>{r.body}</p></div>)}</article>)}
 <form onSubmit={submit}><label className="discovery-field">{reply?'Reply to '+reply.name:'Comment'}{author?' as '+author:''}<textarea ref={input} required maxLength={2000} disabled={!online||busy||loading} value={body} onChange={e=>setBody(e.target.value)}/></label><div className="dialog-actions">{reply&&<button type="button" className="text-button" disabled={busy} onClick={()=>setReply(null)}>Cancel reply</button>}<button type="submit" className="primary compact" disabled={!online||busy||loading||!body.trim()}>{busy?'Posting…':reply?'Post reply':'Post comment'}</button></div></form>
 </section>
}
