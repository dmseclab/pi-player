/* Optional local laboratory renderer. The normal player owns all scheduling. */
const mpvLab = (() => {
  const origin = 'http://127.0.0.1:8000';
  let token = null, active = null;
  if (window.location.origin === origin) {
    try {
      const fragment = new URLSearchParams(window.location.hash.slice(1)).get('mpv-lab');
      if (/^[a-f0-9]{64}$/.test(fragment || '')) {
        sessionStorage.setItem('pi-player-mpv-lab', fragment);
        history.replaceState(null, '', '/player');
      }
      token = sessionStorage.getItem('pi-player-mpv-lab');
      if (!/^[a-f0-9]{64}$/.test(token || '')) token = null;
    } catch (_) { token = null; }
  }
  function exchange(action, item, onState) {
    return new Promise(resolve => {
      let ws, heartbeat, deadline, settled = false;
      const finish = result => {
        if (settled) return;
        settled = true; clearInterval(heartbeat); clearTimeout(deadline);
        if (active?.ws === ws) active = null;
        try { ws?.close(); } catch (_) {}
        resolve(result);
      };
      try { ws = new WebSocket('ws://127.0.0.1:8000/api/player/mpv-lab'); }
      catch (_) { finish({state:'unknown',clean:false}); return; }
      if (action === 'start') active = {ws, finish};
      const arm = () => {
        clearTimeout(deadline);
        deadline = setTimeout(() => finish({state:'unknown',clean:false}), action==='check'?5000:35000);
      };
      arm();
      ws.onopen = () => {
        ws.send(JSON.stringify({action, token, ...(item ? {item_id:item.id} : {})}));
        if (action === 'start') heartbeat = setInterval(() => {
          if (ws.readyState === 1) ws.send(JSON.stringify({action:'ping'}));
        }, 3000);
      };
      ws.onmessage = event => {
        let data;
        try { data = JSON.parse(event.data); } catch (_) { finish({clean:false}); return; }
        if (data.state === 'playing' || data.state === 'starting') {
          arm(); onState?.(data.state);
        } else finish(data);
      };
      ws.onerror = ws.onclose = () => finish({state:'unknown',clean:false});
    });
  }
  return {
    enabled: () => !!token,
    supports: item => !!token && item.asset_type === 'video' &&
      item.asset_video_muted && !item.asset_video_loop &&
      item.asset_display_mode === 'fit' && item.asset_mime_type === 'video/mp4' &&
      Number(item.asset_size_bytes) <= 64*1024*1024 && item.asset_file_present !== false,
    play: (item, onState) => exchange('start', item, onState),
    stop: () => {
      if (active) {
        const prior = active;
        try {
          if (prior.ws.readyState === 1) prior.ws.send(JSON.stringify({action:'stop'}));
          else prior.ws.close();
        } catch (_) {}
        prior.finish({state:'unknown',clean:false});
      }
    },
    clean: async () => {
      if (!token) return true;
      for (let i=0;i<10;i++) {
        const result = await exchange('check');
        if (result.clean === true) return true;
        await new Promise(resolve => setTimeout(resolve, 1000));
      }
      return false;
    }
  };
})();
