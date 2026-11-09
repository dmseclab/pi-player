// Per-item playlist scheduling. Loaded after admin.js so it can extend the existing playlist renderer.
(() => {
  const dayNames=['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
  const originalRender=window.renderPlaylistItems;
  if(typeof originalRender!=='function')return;
  function daysFor(item){const raw=item.schedule_weekdays;if(Array.isArray(raw))return raw.map(Number);if(typeof raw==='string'&&raw.length)return raw.split(',').map(Number);return [0,1,2,3,4,5,6];}
  function scheduleSummary(item){if(!item.schedule_enabled)return 'Always';if(item.schedule_mode==='window')return `${item.schedule_start_date||'…'} ${item.schedule_start_time||'00:00'} → ${item.schedule_end_date||'…'} ${item.schedule_end_time||'00:00'}`;const days=daysFor(item);const dayText=days.length===7?'Daily':days.map(d=>dayNames[d]).join(', ');const timeText=item.schedule_start_time||item.schedule_end_time?`${item.schedule_start_time||'00:00'}–${item.schedule_end_time||'23:59'}`:'';const dateText=item.schedule_start_date||item.schedule_end_date?`${item.schedule_start_date||'…'} → ${item.schedule_end_date||'…'}`:'';return [dayText,timeText,dateText].filter(Boolean).join(' · ');}
  window.renderPlaylistItems=function(playlist){if(!playlist.items.length)return '<p class="muted">No playlist items yet.</p>';return `<table class="table"><thead><tr><th>Pos</th><th>Asset</th><th>Display time</th><th>Schedule</th><th>Enabled</th><th></th></tr></thead><tbody>${playlist.items.map(item=>{const asset=state.assets.find(a=>a.id===item.asset_id);const timing=automaticTiming(asset)?`<span class="pill">${timingDescription(asset)}</span>`:`<input data-item-duration="${playlist.id}:${item.id}" type="number" min="1" max="86400" value="${item.duration_seconds}">`;return `<tr><td><input data-item-position="${playlist.id}:${item.id}" type="number" min="0" value="${item.position}"></td><td>${escapeHtml(item.asset_name)}</td><td>${timing}</td><td><button type="button" class="primary schedule-button" data-edit-schedule="${playlist.id}:${item.id}">${escapeHtml(scheduleSummary(item))}</button></td><td><label class="playlist-switch" title="${item.enabled?'Enabled':'Disabled'}"><input data-item-enabled="${playlist.id}:${item.id}" type="checkbox" ${item.enabled?'checked':''} aria-label="Enable ${escapeHtml(item.asset_name)}"><span class="playlist-switch-track" aria-hidden="true"></span></label></td><td><button class="danger" data-delete-item="${playlist.id}:${item.id}">Remove</button></td></tr>`;}).join('')}</tbody></table>`;};
  const style=document.createElement('style');style.textContent=`.schedule-button{min-width:110px;text-align:left;white-space:normal}.schedule-modal{border:0;border-radius:10px;max-width:620px;width:calc(100% - 32px);padding:0;box-shadow:0 20px 60px rgba(0,0,0,.35)}.schedule-modal::backdrop{background:rgba(0,0,0,.45)}.schedule-modal-body{padding:20px}.schedule-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.schedule-days{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}.schedule-days label{display:flex;align-items:center;gap:4px}.schedule-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:18px}.schedule-mode{align-items:center;color:var(--text);cursor:pointer;display:flex;font-size:14px;font-weight:650;gap:10px;margin-bottom:12px;width:max-content}.schedule-mode input{min-height:0;width:auto}.schedule-mode .playlist-switch-track{flex:0 0 auto}@media(max-width:600px){.schedule-grid{grid-template-columns:1fr}}`;document.head.appendChild(style);
  // Exactly one scheduling choice can be selected for each playlist item.
  const dialog=document.createElement('dialog');
  dialog.className='schedule-modal';
  dialog.innerHTML='<form method="dialog" class="schedule-modal-body" id="schedule-form">'+
    '<h3>Item Schedule</h3><p class="muted" id="schedule-asset-name"></p>'+
    '<fieldset class="schedule-choice"><legend>When should this item play?</legend>'+
      '<label><input type="radio" name="schedule-choice" value="always" checked><span>Always</span></label>'+
      '<label><input type="radio" name="schedule-choice" value="window"><span>Scheduled</span></label>'+
      '<label><input type="radio" name="schedule-choice" value="recurring"><span>Recurring</span></label>'+
    '</fieldset>'+
    '<div id="schedule-fields" class="hidden">'+
      '<p class="muted" id="schedule-hint"></p>'+
      '<div id="schedule-recurring" class="hidden"><p class="muted">Choose the weekdays on which this item may play.</p>'+
        '<div class="schedule-days">'+dayNames.map((name,i)=>'<label><input type="checkbox" data-schedule-day="'+i+'"> '+name+'</label>').join('')+'</div>'+
      '</div>'+
      '<div class="schedule-grid">'+
        '<label>Start date <span id="schedule-start-date-optional" class="muted"></span><input id="schedule-start-date" type="date"></label>'+
        '<label>Start time<input id="schedule-start-time" type="time"></label>'+
        '<label>End date <span id="schedule-end-date-optional" class="muted"></span><input id="schedule-end-date" type="date"></label>'+
        '<label>End time<input id="schedule-end-time" type="time"></label>'+
      '</div>'+
    '</div>'+
    '<div class="schedule-actions"><button type="button" id="schedule-cancel">Cancel</button>'+
      '<button type="submit" class="primary" value="save">Save Schedule</button></div>'+
  '</form>';
  document.body.appendChild(dialog);

  style.textContent += '.schedule-choice{border:0;display:flex;gap:0;margin:12px 0 16px;padding:0;min-width:0}'+
    '.schedule-choice legend{font-weight:650;margin-bottom:8px}'+
    '.schedule-choice label{flex:1;min-width:0;cursor:pointer}'+
    '.schedule-choice input{position:absolute;opacity:0;width:1px;height:1px}'+
    '.schedule-choice span{display:block;border:1px solid #b4c1d1;padding:10px 8px;text-align:center;font-weight:600}'+
    '.schedule-choice label:first-of-type span{border-radius:8px 0 0 8px}'+
    '.schedule-choice label:last-of-type span{border-radius:0 8px 8px 0}'+
    '.schedule-choice label+label span{border-left:0}'+
    '.schedule-choice input:checked+span{background:#2563eb;color:white;border-color:#2563eb}'+
    '.schedule-choice input:focus-visible+span{outline:3px solid #93c5fd;outline-offset:2px}';

  let editing=null;
  const field = id => dialog.querySelector('#'+id);
  const choice = () => dialog.querySelector('input[name="schedule-choice"]:checked').value;
  function syncChoice() {
    const mode=choice();
    field('schedule-fields').classList.toggle('hidden', mode==='always');
    field('schedule-recurring').classList.toggle('hidden', mode!=='recurring');
    field('schedule-start-date-optional').textContent=mode==='recurring'?'(optional)':'';
    field('schedule-end-date-optional').textContent=mode==='recurring'?'(optional)':'';
    field('schedule-start-date').required=mode==='window';
    field('schedule-end-date').required=mode==='window';
    field('schedule-start-time').required=mode==='window'||mode==='recurring';
    field('schedule-end-time').required=mode==='window'||mode==='recurring';
    field('schedule-hint').textContent=mode==='window'
      ? 'Play continuously between the chosen start and end. End is exclusive. Pi local time (SAST).'
      : 'Play only on selected weekdays between the chosen times. Optional dates limit the recurring period. Pi local time (SAST).';
  }
  dialog.querySelectorAll('input[name="schedule-choice"]').forEach(input=>input.addEventListener('change',syncChoice));
  field('schedule-cancel').addEventListener('click',()=>{editing=null;dialog.close();});

  document.addEventListener('click',event=>{
    const button=event.target.closest('[data-edit-schedule]');
    if(!button)return;
    const [playlistId,itemId]=button.dataset.editSchedule.split(':');
    const playlist=state.playlists.find(p=>p.id===playlistId);
    const item=playlist?.items.find(i=>i.id===itemId);
    if(!item)return;
    editing={playlistId,itemId};
    field('schedule-asset-name').textContent=item.asset_name;
    const mode=!item.schedule_enabled?'always':item.schedule_mode==='window'?'window':'recurring';
    dialog.querySelector('input[name="schedule-choice"][value="'+mode+'"]').checked=true;
    const selected=new Set(daysFor(item));
    dialog.querySelectorAll('[data-schedule-day]').forEach(box=>box.checked=selected.has(Number(box.dataset.scheduleDay)));
    field('schedule-start-time').value=item.schedule_start_time||'';
    field('schedule-end-time').value=item.schedule_end_time||'';
    field('schedule-start-date').value=item.schedule_start_date||'';
    field('schedule-end-date').value=item.schedule_end_date||'';
    syncChoice();
    dialog.showModal();
  });

  field('schedule-form').addEventListener('submit',async event=>{
    event.preventDefault();
    if(!editing)return;
    const mode=choice();
    const weekdays=[...dialog.querySelectorAll('[data-schedule-day]:checked')].map(box=>Number(box.dataset.scheduleDay));
    const sd=field('schedule-start-date').value;
    const ed=field('schedule-end-date').value;
    const st=field('schedule-start-time').value;
    const et=field('schedule-end-time').value;
    if(mode==='recurring'&&!weekdays.length){alert('Select at least one weekday.');return;}
    if(mode==='recurring'&&(!st||!et)){alert('Select start and end times for recurring playback.');return;}
    if(mode==='recurring'&&sd&&ed&&sd>ed){alert('End date must be on or after start date.');return;}
    if(mode==='window'&&(!sd||!ed||!st||!et||sd+'T'+st>=ed+'T'+et)){
      alert('Enter valid start and end dates/times. End must be later than start.');return;
    }
    // Always clears the old schedule, not the playlist Enabled switch.
    const payload=mode==='always'
      ? {schedule_enabled:false,schedule_mode:'recurring',schedule_start_date:null,schedule_end_date:null,
         schedule_weekdays:[0,1,2,3,4,5,6],schedule_start_time:null,schedule_end_time:null}
      : {schedule_enabled:true,schedule_mode:mode,schedule_start_date:sd||null,schedule_end_date:ed||null,
         schedule_weekdays:mode==='recurring'?weekdays:[0,1,2,3,4,5,6],
         schedule_start_time:st||null,schedule_end_time:et||null};
    try{
      await api('/api/playlists/'+editing.playlistId+'/items/'+editing.itemId,
        {method:'PUT',body:JSON.stringify(payload)});
      dialog.close();editing=null;await loadPlaylists();
    }catch(error){alert(error.message||'Unable to save schedule');}
  });
  // The first playlist render may have completed before this extension loaded.
  if(state.playlists.length)loadPlaylists().catch(console.error);
})();
