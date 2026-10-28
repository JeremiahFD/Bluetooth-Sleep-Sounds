export function rememberProfileEnabled(storage){
 try{return storage.getItem('sleep-remember-profile')!=='false'}catch{return true}
}
export function shouldPromptForProfile({enabled,valid,remember,saved,confirmed}){
 return !!enabled && (!valid || !(remember && saved) && !confirmed);
}
