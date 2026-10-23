// NTP configuration/status for the Settings page.
(() => {
  const nameInput=document.querySelector('#setting-player-name');
  const form=document.querySelector('#settings-form');
  if(!nameInput||!form)return;

  const row=document.createElement('div');
  row.className='form-row';
  row.innerHTML='<label for="setting-ntp-server">NTP Server</label><input id="setting-ntp-server" placeholder="e.g. 172.18.5.20" required><small id="setting-ntp-status" class="muted">Checking time synchronization…</small>';
  nameInput.closest('.form-row').insertAdjacentElement('afterend',row);

  const input=row.querySelector('#setting-ntp-server');
  const status=row.querySelector('#setting-ntp-status');

  function render(data){
    input.value=data.configured_server||input.value||'';
    const state=data.synchronized?'Synchronized':'Not synchronized';
    const server=data.server_address||data.server_name||data.configured_server||'Not configured';
    const zone=data.timezone||'Unknown';
    status.textContent=`Time sync: ${state} · Server: ${server} · Time zone: ${zone}`;
  }

  async function load(){
    try{render(await api('/api/system/ntp'));}
    catch(error){status.textContent=`Time sync status unavailable: ${error.message}`;}
  }

  form.addEventListener('submit',async event=>{
    const server=input.value.trim();
    if(!server)return;
    status.textContent='Applying NTP server…';
    try{
      const result=await api('/api/system/ntp',{method:'PUT',body:JSON.stringify({server})});
      render(result);
      setTimeout(()=>load().catch(console.warn),3000);
    }catch(error){
      status.textContent=`NTP update failed: ${error.message}`;
    }
  });

  load();
  setInterval(()=>{
    if(!document.querySelector('#tab-settings')?.classList.contains('hidden'))load().catch(console.warn);
  },10000);
})();
