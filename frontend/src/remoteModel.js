export const AXIS_NAMES={0:'Left stick horizontal',1:'Left stick vertical',2:'Axis Z / left trigger',3:'Right stick horizontal',4:'Right stick vertical',5:'Axis RZ / right trigger',16:'D-pad horizontal',17:'D-pad vertical'};
const KEY_NAMES={28:'Enter',57:'Space',103:'Up',105:'Left',106:'Right',108:'Down',113:'Mute',114:'Volume down',115:'Volume up',164:'Play / pause',165:'Previous',163:'Next',256:'Button 0',257:'Button 1',258:'Button 2',259:'Button 3',272:'Mouse left',273:'Mouse right',274:'Mouse middle',304:'A / South',305:'B / East',307:'X / North',308:'Y / West',310:'Left shoulder',311:'Right shoulder',312:'Left trigger',313:'Right trigger',314:'Select',315:'Start',317:'Left stick click',318:'Right stick click'};
export function tokenLabel(token){if(token.startsWith('k:'))return KEY_NAMES[+token.slice(2)]||`Button ${token.slice(2)}`;const [,code,direction]=token.split(':');return `${AXIS_NAMES[code]||'Axis '+code} ${direction==='+'?'positive':'negative'}`;}
export function bindingLabel(row){return row.tokens?.length?row.tokens.map(tokenLabel).join(' + '):'Click, then press a button';}
export function assignBinding(layout,index,captured){
 if(!Number.isInteger(index)||index<0||index>layout.bindings.length)throw new Error('Choose an existing assignment or add a new one.');
 if(index===layout.bindings.length&&layout.bindings.length>=48)throw new Error('This layout has reached 48 assignments.');
 if(!Array.isArray(captured.tokens)||captured.tokens.length<1||captured.tokens.length>4)throw new Error('Capture one to four inputs before adding an assignment.');
 const rows=layout.bindings.map(r=>({...r,tokens:[...r.tokens]}));
 const target={...(rows[index]||{action:'play_pause'}),tokens:[...captured.tokens].sort(),modified:!!captured.modified};
 const signature=r=>`${r.modified}:${[...r.tokens].sort().join(',')}`;
 const conflict=rows.findIndex((r,i)=>i!==index&&signature(r)===signature(target));
 rows[index]=target;
 if(conflict>=0)rows.splice(conflict,1);
 return {layout:{...layout,bindings:rows},moved:conflict>=0};
}
export function manualAssignment(layout,index,input){
 if(input.modified&&!layout.modifiers.length)throw new Error('Assign a modifier first, or turn off With modifier.');
 const code=Number(input.code);
 if(String(input.code).trim()===''||!Number.isInteger(code)||code<0||code>767)throw new Error('Enter a whole button code from 0 to 767.');
 if(!['key','axis'].includes(input.kind))throw new Error('Choose a button or stick direction.');
 if(input.kind==='axis'&&(!Object.hasOwn(AXIS_NAMES,code)||!['+','-'].includes(input.direction)))throw new Error('Choose a supported axis and direction.');
 return assignBinding(layout,index,{tokens:[input.kind==='key'?'k:'+code:'a:'+code+':'+input.direction],modified:input.modified});
}
export function layoutPayload(layout){return Object.fromEntries(['name','bindings','modifiers','any_button','any_action','regular_delay','modified_delay','dead_zone'].map(k=>[k,k==='bindings'?layout.bindings.map(({tokens,modified,action})=>({tokens,modified,action})):['regular_delay','modified_delay','dead_zone'].includes(k)?Number(layout[k]):layout[k]]));}
export function remotePayload(remote){return Object.fromEntries(['name','enabled','app_only','profile','layout','default_track'].map(k=>[k,remote[k]]));}
export function vncDestination(hostname){const host=['localhost','127.0.0.1','[::1]'].includes(hostname)?'127.0.0.1':hostname;return {address:`${host}:5900`,url:`vnc://${host}:5900`};}
