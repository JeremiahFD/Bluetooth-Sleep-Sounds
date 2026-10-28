// Saved only in the selected Pi profile; absent keys retain backward-compatible defaults.
export function browsingPreferences(values){
 return {
  openNowPlayingOnSelect: values?.open_now_playing_on_select===true,
  showMiniPlayer: values?.show_mini_player!==false
 };
}
export function miniPlayerTrack(status,tracks,selected){
 if(!status)return null;
 return tracks.find(t=>t.id===status.selected)
     || (status.idle?tracks.find(t=>t.id===selected):null);
}
export function shouldShowMiniPlayer(page,status,track,values){
 return page!=='home' && !!track && browsingPreferences(values).showMiniPlayer;
}
