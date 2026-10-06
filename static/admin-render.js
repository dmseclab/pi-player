// Render controls once with their rows. No MutationObservers or post-render rewrites.
function modeOptions(value, modes=['fit','fill','stretch']) {
  return modes.map(mode=>`<option value="${mode}" ${mode===value?'selected':''}>${mode[0].toUpperCase()+mode.slice(1)}</option>`).join('');
}
function assetPreview(asset) {
  return asset.type==='image'?`<img class="asset-preview" loading="lazy" src="${asset.media_url}" alt="">`:`<span class="pill">${asset.type==='pdf'?'PDF':asset.type==='video'?'Video':'Web'}</span>`;
}
function assetDetails(asset) {
  if(asset.type==='website')return `${escapeHtml(asset.url)}<br><span class="pill">${escapeHtml(asset.display_mode)}</span> · ${Number(asset.zoom_percent||100)}%`;
  let result=escapeHtml(bytes(asset.size_bytes));
  if(asset.type==='pdf')result+=`<br>${asset.pdf_page_count||'?'} page(s) · ${asset.pdf_page_seconds||10} seconds/page · ${asset.pdf_play_once?'All pages once':'Timed slot'}${asset.pdf_metadata_error?`<br>${escapeHtml(asset.pdf_metadata_error)}`:''}`;
  else result+=`<br><span class="pill">${escapeHtml(asset.display_mode||'fit')}</span>${asset.type==='video'?` · ${asset.video_muted?'Muted':'Audio'}${asset.video_loop?' · Loop':''}`:''}`;
  return result;
}
function assetEditControls(asset) {
  if(asset.type==='pdf')return `<p>${asset.pdf_page_count||'?'} page(s)</p><label>Seconds per page<input data-asset-edit-pdf-seconds type="number" min="1" max="86400" value="${asset.pdf_page_seconds||10}"></label><label><input type="checkbox" data-asset-edit-pdf-once ${asset.pdf_play_once?'checked':''}> Play all pages once</label>`;
  const modes=asset.type==='website'?['embed','direct']:['fit','fill','stretch'];
  let html=`<label>Display mode<select data-asset-edit-display-mode>${modeOptions(asset.display_mode||modes[0],modes)}</select></label>`;
  if(asset.type==='video')html+=`<label><input type="checkbox" data-video-muted ${asset.video_muted?'checked':''}> Muted</label><label><input type="checkbox" data-video-loop ${asset.video_loop?'checked':''}> Loop video for the playlist slot</label>`;
  if(asset.type==='website')html=`<label>Website URL<input data-asset-edit-url value="${escapeAttr(asset.url||'')}"></label>`+html+`<label>Zoom (%)<input data-asset-edit-zoom type="number" min="50" max="200" value="${asset.zoom_percent||100}"></label><label>Reload every (seconds, 0 = each visit)<input data-asset-edit-reload type="number" min="0" max="86400" value="${asset.reload_seconds||0}"></label><button type="button" data-test-link="${escapeAttr(asset.url)}">Test Link</button>`;
  return html;
}
function automaticTiming(asset) {return asset?.type==='video'&&!asset.video_loop || asset?.type==='pdf'&&!!asset.pdf_play_once;}
function timingDescription(asset) {
  if(asset?.type==='pdf'&&asset.pdf_play_once)return `${asset.pdf_page_count||'?'} × ${asset.pdf_page_seconds||10}s — all pages once`;
  return 'Auto — video length';
}
function syncAddItemTiming(form) {
  const asset=state.assets.find(a=>a.id===form.querySelector('[name="asset_id"]').value);
  const input=form.querySelector('[name="duration_seconds"]'),label=form.querySelector('[data-timer-label]');
  if(automaticTiming(asset)){
    if(!input.disabled)input.dataset.previousValue=input.value||'15';
    input.disabled=true;input.value='';input.placeholder='Auto';label.textContent=timingDescription(asset);
  }else{input.disabled=false;if(!input.value)input.value=input.dataset.previousValue||'15';input.placeholder='';label.textContent='Display time (seconds)';}
}
function initializeAdminControls() {
  const upload=document.querySelector('#upload-form');
  upload.querySelector('.asset-actions').insertAdjacentHTML('beforebegin','<div id="video-upload-options" class="hidden"><label><input type="checkbox" name="video_muted" checked> Muted</label><label><input type="checkbox" name="video_loop"> Loop video</label></div>');
  document.querySelector('#pdf-page-seconds').parentElement.insertAdjacentHTML('beforeend','<label><input type="checkbox" name="pdf_play_once"> Play all pages once</label>');
  const file=document.querySelector('#asset-file');
  const sync=()=>{document.querySelector('#video-upload-options').classList.toggle('hidden',!file.files?.[0]?.name.match(/\.(mp4|webm)$/i));};
  file.addEventListener('change',sync);upload.addEventListener('reset',()=>setTimeout(sync,0));
  upload.addEventListener('formdata',e=>{for(const field of ['video_muted','video_loop','pdf_play_once'])e.formData.set(field,String(!!upload.querySelector(`[name="${field}"]`)?.checked));});
  document.querySelector('#link-form .asset-actions').insertAdjacentHTML('beforebegin','<label>Zoom (%)<input id="link-zoom-percent" type="number" min="50" max="200" value="100"></label><label>Reload every (seconds, 0 = each visit)<input id="link-reload-seconds" type="number" min="0" max="86400" value="0"></label><button type="button" id="test-link">Test Link</button>');
  document.querySelector('#playlist-form').insertAdjacentHTML('afterend','<div class="toolbar"><button type="button" id="import-playlist">Import Playlist Package</button><input id="playlist-package-file" type="file" accept=".zip" hidden></div>');
}
async function refreshAssetsAndPlaylists(){await loadAssets();await Promise.all([loadPlaylists(),loadStatus()]);}
