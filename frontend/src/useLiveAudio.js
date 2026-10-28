import {useEffect,useRef,useState} from 'react';
import {LiveAudioEditor} from './liveAudioEditor.js';

export default function useLiveAudio({config,api,refresh,enabled}){
 const latest=useRef({api,refresh});latest.current={api,refresh};
 const editorRef=useRef(null);
 if(!editorRef.current)editorRef.current=new LiveAudioEditor({config,save:patch=>latest.current.api.saveLiveAudio(patch),onSaved:()=>latest.current.refresh()});
 const editor=editorRef.current;
 const [state,setState]=useState(()=>editor.snapshot());
 useEffect(()=>{editor.disposed=false;editor.onChange=setState;return()=>editor.dispose();},[editor]);
 useEffect(()=>editor.receive(config),[editor,config]);
 useEffect(()=>editor.setEnabled(enabled),[editor,enabled]);
 return {...state,edit:patch=>editor.edit(patch),commit:()=>editor.flush(),reload:()=>editor.discard(config)};
}
