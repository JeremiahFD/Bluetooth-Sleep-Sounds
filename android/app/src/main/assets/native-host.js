(()=>{if(window.__sleepHostObserver)window.__sleepHostObserver.disconnect();
const mount=()=>{const header=document.querySelector('.top-actions')||document.querySelector('header');if(!header)return;
document.documentElement.dataset.sleepNativeHost='true';
if(!document.querySelector('link[data-native-host-style]')){const css=document.createElement('link');css.rel='stylesheet';css.href='/ui/native-host.css';css.dataset.nativeHostStyle='true';document.head.append(css);}
let link=document.getElementById('sleep-native-host');if(!link){link=document.createElement('a');link.id='sleep-native-host';link.className='native-host-selector';link.href='sleep-sounds://devices';header.prepend(link);}
const label=window.__sleepHostLabel||'Sleep device';if(link.textContent!==label+' ▾')link.textContent=label+' ▾';link.setAttribute('aria-label','Choose sleep device: '+label);link.title=label;};
mount();window.__sleepHostObserver=new MutationObserver(mount);window.__sleepHostObserver.observe(document.body,{childList:true,subtree:true});})();
