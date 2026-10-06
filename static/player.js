const stage = document.querySelector('#stage');
let playlistSignature='', items=[], index=0, timer=null, reloadTimer=null;
let directWindow=null, currentVideo=null, videoMonitor=null, videoStartupTimer=null, videoHardTimer=null, stopPdf=null;
let bootSplashUntil=Date.now()+5000, playerInfo=null, generation=0, refreshing=false, currentItem=null;
let reportQueue=Promise.resolve(), lastProgressReport=0;
const localKiosk=['127.0.0.1','localhost','[::1]'].includes(window.location.hostname);
function escapeHtml(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));}
function report(event, message=null, page=null) {
  if(!localKiosk)return;
  const body={event,asset_id:currentItem?.asset_id||null,message:message?String(message).slice(0,500):null,page};
  reportQueue=reportQueue.catch(()=>{}).then(async()=>{
    try {await fetch('/api/player/report',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(3000)});}catch(_){}
  });
}
async function loadPlayerInfo(){try{const r=await fetch('/api/player/info',{cache:'no-store',signal:AbortSignal.timeout(5000)});if(r.ok)playerInfo=await r.json();}catch(_){}}
function splash(waiting=false){const ip=playerInfo?.ip_addresses?.[0]||'Waiting for network...',host=playerInfo?.hostname||'pi-player';stage.innerHTML=`<div class="player-message"><div style="font-size:2em;font-weight:700;margin-bottom:.6em">PI PLAYER</div><div>Hostname: ${escapeHtml(host)}</div><div>IP Address: ${escapeHtml(ip)}</div><div>Admin: ${ip.includes('.')?`http://${escapeHtml(ip)}:8000`:'Waiting for network...'}</div><div style="margin-top:1em">${playerInfo?.setup_required?'First-time setup required':waiting?'Ready for configuration':'Starting playlist...'}</div></div>`;}
function signature(d){return JSON.stringify({state:d.state,playlist:d.playlist?.id,items:d.items.filter(i=>i.enabled).map(i=>[i.id,i.position,i.duration_seconds,i.asset_id,i.asset_type,i.asset_url,i.media_url,i.asset_display_mode,i.asset_zoom_percent,i.asset_reload_seconds,i.asset_video_muted,i.asset_video_loop,i.asset_pdf_page_seconds,i.asset_pdf_play_once,i.asset_file_present])});}
async function loadPlaylist(){
  if(refreshing)return;refreshing=true;
  try{
    const r=await fetch('/api/player/playlist',{cache:'no-store',signal:AbortSignal.timeout(5000)});
    if(!r.ok)throw Error(`Playlist HTTP ${r.status}`);
    const d=await r.json();
    if(!Array.isArray(d.items)||!['playing','stopped'].includes(d.state))throw Error('Invalid playlist response');
    const s=signature(d);report('playlist_ok');
    if(s!==playlistSignature){playlistSignature=s;items=d.state==='playing'?d.items.filter(i=>i.enabled):[];index=0;playCurrent();}
  }catch(error){
    console.warn('Playlist refresh failed; retaining last valid playlist',error);
    report('playlist_error',error.message);
    // Keep the current DOM, timers and last known playlist running.
    if(!playlistSignature&&!items.length)splash(true);
  }finally{refreshing=false;}
}
function objectFit(m){return m==='fill'?'cover':m==='stretch'?'fill':'contain';}
function clearWebsiteReload(){clearInterval(reloadTimer);reloadTimer=null;}
function closeDirectWindow(){if(directWindow){try{if(!directWindow.closed)directWindow.close();}catch(_){}directWindow=null;try{window.focus();}catch(_){}}}
function applyEmbedZoom(f,z){const n=Math.min(200,Math.max(50,Number(z||100)))/100;f.style.transformOrigin='top left';f.style.transform=`scale(${n})`;f.style.width=`${100/n}vw`;f.style.height=`${100/n}vh`;}
function cleanupCurrentVideo(){
  clearInterval(videoMonitor);clearTimeout(videoStartupTimer);clearTimeout(videoHardTimer);
  videoMonitor=videoStartupTimer=videoHardTimer=null;
  const v=currentVideo;currentVideo=null;
  if(v){try{v.pause();v.removeAttribute('src');v.load();v.remove();}catch(_){}}
}
function failCurrent(reason,token=generation){
  if(token!==generation)return;
  console.error('Skipping asset',currentItem?.asset_id,reason);report('error',reason);
  cleanupCurrentVideo();if(stopPdf)stopPdf();stopPdf=null;
  stage.replaceChildren();advanceSoon();
}
function playVideo(item,durationMs,token){
  if(item.asset_file_present===false||!item.media_url){failCurrent('Video file missing',token);return;}
  stage.replaceChildren();const video=document.createElement('video');currentVideo=video;
  video.id='player-video';video.autoplay=true;video.playsInline=true;video.preload='auto';
  video.muted=!!item.asset_video_muted;video.loop=!!item.asset_video_loop;video.style.objectFit=objectFit(item.asset_display_mode);
  let lastTime=0,lastProgress=Date.now(),recoveryAttempted=false,started=false;
  const alive=()=>token===generation&&currentVideo===video;
  const progress=()=>{
    if(!alive())return;const now=Number(video.currentTime||0);
    if(Math.abs(now-lastTime)>0.05){lastTime=now;lastProgress=Date.now();recoveryAttempted=false;
      if(Date.now()-lastProgressReport>10000){lastProgressReport=Date.now();report('progress');}}
  };
  videoStartupTimer=setTimeout(()=>{if(alive())failCurrent('Video did not start within 30 seconds',token);},30000);
  video.addEventListener('loadedmetadata',()=>{
    if(alive()&&Number.isFinite(video.duration)&&video.duration>0&&!video.loop)
      videoHardTimer=setTimeout(()=>{if(alive())failCurrent('Video exceeded its playback safety limit',token);},Math.ceil(video.duration*1000)+60000);
  },{once:true});
  video.addEventListener('playing',()=>{
    if(!alive())return;lastProgress=Date.now();clearTimeout(videoStartupTimer);videoStartupTimer=null;
    if(!started){started=true;report('ready');if(video.loop)timer=setTimeout(advance,durationMs);}
  });
  video.addEventListener('timeupdate',progress);
  video.addEventListener('error',()=>{if(alive())failCurrent(`Video media error ${video.error?.code||0}`,token);},{once:true});
  if(!video.loop)video.addEventListener('ended',()=>{if(alive())advance();},{once:true});
  stage.appendChild(video);video.src=item.media_url;video.load();
  const start=()=>{if(alive())video.play().catch(error=>{if(alive())failCurrent(error.message||'Video autoplay failed',token);});};
  if(video.readyState>=2)start();else video.addEventListener('canplay',start,{once:true});
  videoMonitor=setInterval(()=>{
    if(!alive()||!started||video.ended)return;progress();if(Date.now()-lastProgress<15000)return;
    if(!recoveryAttempted){recoveryAttempted=true;lastProgress=Date.now();video.play().catch(()=>{});return;}
    failCurrent('Video stalled after a recovery attempt',token);
  },5000);
}
function playCurrent(){
  generation++;const token=generation;
  clearTimeout(timer);timer=null;if(stopPdf)stopPdf();stopPdf=null;
  cleanupCurrentVideo();clearWebsiteReload();closeDirectWindow();
  if(Date.now()<bootSplashUntil){splash(false);timer=setTimeout(playCurrent,Math.max(100,bootSplashUntil-Date.now()));return;}
  if(!items.length){currentItem=null;report('idle');splash(true);return;}
  const item=items[index%items.length];currentItem=item;report('selected');
  const durationMs=Math.max(1,Number(item.duration_seconds)||15)*1000,reloadSeconds=Math.max(0,Number(item.asset_reload_seconds)||0);
  if(item.asset_type==='image'){
    if(item.asset_file_present===false){failCurrent('Image file missing',token);return;}
    stage.replaceChildren();const img=document.createElement('img');img.id='player-image';img.alt=item.asset_name;img.style.objectFit=objectFit(item.asset_display_mode);
    timer=setTimeout(()=>failCurrent('Image loading timed out',token),30000);
    img.addEventListener('load',()=>{if(token!==generation)return;clearTimeout(timer);report('ready');timer=setTimeout(advance,durationMs);},{once:true});
    img.addEventListener('error',()=>failCurrent('Image failed to load',token),{once:true});stage.appendChild(img);img.src=item.media_url;return;
  }
  if(item.asset_type==='pdf'){
    if(item.asset_file_present===false){failCurrent('PDF file missing',token);return;}
    stage.replaceChildren();
    stopPdf=startPdfPlayback(item,stage,()=>{if(token!==generation)return;report('ready',null,1);if(!item.asset_pdf_play_once)timer=setTimeout(advance,durationMs);},error=>failCurrent(error.message||'PDF rendering failed',token),()=>{if(token===generation)advance();},page=>{if(token===generation)report('progress',null,page);});return;
  }
  if(item.asset_type==='video'){playVideo(item,durationMs,token);return;}
  if(item.asset_type==='website'){
    if(item.asset_display_mode==='direct'){
      directWindow=window.open(item.asset_url,'pi-player-direct');if(!directWindow){failCurrent('Direct website could not open',token);return;}
      try{directWindow.focus();}catch(_){}report('ready');
      if(reloadSeconds>0)reloadTimer=setInterval(()=>{try{if(directWindow&&!directWindow.closed)directWindow.location.href=item.asset_url;}catch(_){}},reloadSeconds*1000);
    }else{
      stage.replaceChildren();const frame=document.createElement('iframe');frame.id='player-web';frame.title=item.asset_name;applyEmbedZoom(frame,item.asset_zoom_percent);
      frame.addEventListener('load',()=>{if(token===generation)report('ready');},{once:true});stage.appendChild(frame);frame.src=item.asset_url;
      if(reloadSeconds>0)reloadTimer=setInterval(()=>{if(token===generation)frame.src=item.asset_url;},reloadSeconds*1000);
    }
    timer=setTimeout(advance,durationMs);return;
  }
  failCurrent(`Unsupported asset type ${item.asset_type}`,token);
}
function advance(){if(items.length)index=(index+1)%items.length;playCurrent();}
function advanceSoon(){clearTimeout(timer);clearWebsiteReload();timer=setTimeout(advance,2000);}
window.addEventListener('beforeunload',()=>{generation++;if(stopPdf)stopPdf();cleanupCurrentVideo();clearWebsiteReload();closeDirectWindow();});
setInterval(()=>report('heartbeat'),10000);
loadPlayerInfo().finally(()=>{splash(false);loadPlaylist();});setInterval(loadPlaylist,5000);
