// Read-only appliance identity display for the admin UI.
async function loadPlayerIdentity() {
  try {
    const response = await fetch('/api/player/info', { credentials: 'same-origin' });
    if (!response.ok) return;

    const info = await response.json();
    if (!info.player_id) return;

    const dashboardId = document.querySelector('#status-player-id');
    if (dashboardId) dashboardId.textContent = info.player_id;

    const settingsId = document.querySelector('#setting-player-id');
    if (settingsId) settingsId.value = info.player_id;
  } catch (_) {
    // Identity display is informational and must never block admin operation.
  }
}

document.addEventListener('DOMContentLoaded', loadPlayerIdentity);
