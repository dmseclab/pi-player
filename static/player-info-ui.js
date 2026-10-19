// Read-only appliance identity display for the admin UI.
async function loadPlayerIdentity() {
  try {
    const response = await fetch('/api/player/info', { credentials: 'same-origin' });
    if (!response.ok) return;
    const info = await response.json();
    if (!info.player_id) return;

    const settingsGrid = document.querySelector('#settings-form .grid.two');
    if (settingsGrid && !document.querySelector('#setting-player-id')) {
      const row = document.createElement('div');
      row.className = 'form-row';
      row.innerHTML = '<label for="setting-player-id">Player ID</label><input id="setting-player-id" readonly aria-readonly="true">';
      row.querySelector('input').value = info.player_id;
      settingsGrid.prepend(row);
    }

    const status = document.querySelector('#status-content');
    if (status && !document.querySelector('#status-player-id')) {
      const item = document.createElement('div');
      item.id = 'status-player-id';
      item.innerHTML = '<strong>Player ID</strong><br><span class="muted"></span>';
      item.querySelector('.muted').textContent = info.player_id;
      status.prepend(item);
    }
  } catch (_) {
    // Identity display is informational and must never block admin operation.
  }
}

document.addEventListener('DOMContentLoaded', () => {
  const observer = new MutationObserver(() => loadPlayerIdentity());
  const status = document.querySelector('#status-content');
  if (status) observer.observe(status, { childList: true });
  loadPlayerIdentity();
});
