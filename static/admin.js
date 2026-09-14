const state = {
  assets: [],
  playlists: [],
  settings: null,
  editingAssetId: null,
};

const $ = (selector) => document.querySelector(selector);

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: options.body instanceof FormData ? {} : { "Content-Type": "application/json" },
    ...options,
  });
  if (response.status === 401) {
    showLogin();
    throw new Error("Login required");
  }
  const text = await response.text();
  const data = text ? JSON.parse(text) : {};
  if (!response.ok) {
    throw new Error(data.detail || "Request failed");
  }
  return data;
}

function showLogin(message = "") {
  $("#login").classList.remove("hidden");
  $("#app").classList.add("hidden");
  $("#login-message").innerHTML = message ? `<div class="message error">${escapeHtml(message)}</div>` : "";
}

function showApp() {
  $("#login").classList.add("hidden");
  $("#app").classList.remove("hidden");
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[char]));
}

function escapeAttr(value) {
  return escapeHtml(value);
}

function bytes(value) {
  if (!value) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(index ? 1 : 0)} ${units[index]}`;
}

function setTab(name) {
  document.querySelectorAll(".nav-button").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === name);
  });
  document.querySelectorAll(".tab").forEach((tab) => tab.classList.add("hidden"));
  $(`#tab-${name}`).classList.remove("hidden");
}

async function loadAll() {
  showApp();
  await Promise.all([loadStatus(), loadAssets(), loadPlaylists(), loadSettings(), loadLogs()]);
}

async function loadStatus() {
  const status = await api("/api/status");
  $("#player-name").textContent = status.player_name;
  const isPlaying = status.playback.state === "playing";
  $("#start-playback").disabled = isPlaying;
  $("#stop-playback").disabled = !isPlaying;
  const diskUsed = status.disk.total ? Math.round((status.disk.used / status.disk.total) * 100) : 0;
  $("#status-content").innerHTML = `
    <div><strong>Playback</strong><br><span class="muted">${escapeHtml(status.playback.state)}</span></div>
    <div><strong>Active playlist</strong><br><span class="muted">${escapeHtml(status.active_playlist?.name || "None")}</span></div>
    <div><strong>Host</strong><br><span class="muted">${escapeHtml(status.host)}</span></div>
    <div><strong>IP addresses</strong><br><span class="muted">${escapeHtml(status.ip_addresses.join(", ") || "Unknown")}</span></div>
    <div><strong>Assets</strong><br><span class="muted">${status.asset_count}</span></div>
    <div><strong>Disk</strong><br><span class="muted">${bytes(status.disk.free)} free, ${diskUsed}% used</span></div>
    <div><strong>SSH</strong><br><span class="muted">Port ${status.ssh_port}</span></div>
    <div><strong>Version</strong><br><span class="muted">${escapeHtml(status.version)}</span></div>
  `;
}

async function loadSettings() {
  state.settings = await api("/api/settings");
  $("#setting-player-name").value = state.settings.player_name;
  $("#setting-max-upload").value = state.settings.max_upload_mb;
  $("#setting-username").value = state.settings.admin_username;
}

async function loadAssets() {
  state.assets = await api("/api/assets");
  if (!state.assets.length) {
    $("#asset-list").innerHTML = `<p class="muted">No assets yet.</p>`;
    return;
  }
  $("#asset-list").innerHTML = `
    <table class="table">
      <thead><tr><th>Preview</th><th>Name</th><th>Type</th><th>Details</th><th></th></tr></thead>
      <tbody>
        ${state.assets.map((asset) => state.editingAssetId === asset.id ? renderAssetEditRow(asset) : `
          <tr>
            <td>${asset.type === "image" ? `<img class="asset-preview" src="${asset.media_url}" alt="">` : `<span class="pill">Web</span>`}</td>
            <td>${escapeHtml(asset.name)}</td>
            <td>${escapeHtml(asset.type)}</td>
            <td class="muted">${asset.type === "website" ? `${escapeHtml(asset.url)}<br><span class="pill">${escapeHtml(asset.display_mode || "embed")}</span>` : escapeHtml(bytes(asset.size_bytes))}</td>
            <td>
              <button data-edit-asset="${asset.id}">Edit</button>
              <button class="danger" data-delete-asset="${asset.id}">Delete</button>
            </td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
}

function renderAssetEditRow(asset) {
  return `
    <tr data-editing-asset="${asset.id}">
      <td>${asset.type === "image" ? `<img class="asset-preview" src="${asset.media_url}" alt="">` : `<span class="pill">Web</span>`}</td>
      <td>
        <input data-asset-edit-name value="${escapeAttr(asset.name)}" aria-label="Asset name">
      </td>
      <td>${escapeHtml(asset.type)}</td>
      <td>
        ${asset.type === "website"
          ? `<div class="form-row"><input data-asset-edit-url value="${escapeAttr(asset.url || "")}" aria-label="Website URL"></div>
             <select data-asset-edit-display-mode aria-label="Website display mode">
               <option value="embed" ${(asset.display_mode || "embed") === "embed" ? "selected" : ""}>Embed</option>
               <option value="direct" ${asset.display_mode === "direct" ? "selected" : ""}>Direct</option>
             </select>`
          : `<span class="muted">${escapeHtml(bytes(asset.size_bytes))}</span>`}
      </td>
      <td>
        <button class="primary" data-save-asset="${asset.id}">Save</button>
        <button data-cancel-asset-edit="${asset.id}">Cancel</button>
      </td>
    </tr>
  `;
}

async function loadPlaylists() {
  state.playlists = await api("/api/playlists");
  if (!state.playlists.length) {
    $("#playlist-list").innerHTML = `<p class="muted">No playlists yet.</p>`;
    return;
  }
  $("#playlist-list").innerHTML = state.playlists.map((playlist) => `
    <section class="panel">
      <div class="toolbar">
        <h3>${escapeHtml(playlist.name)} ${playlist.is_active ? `<span class="pill">Active</span>` : ""}</h3>
        <button data-activate-playlist="${playlist.id}">Activate</button>
        <button class="danger" data-delete-playlist="${playlist.id}">Delete</button>
      </div>
      <form class="toolbar" data-add-item="${playlist.id}">
        <select name="asset_id" required>
          <option value="">Select asset</option>
          ${state.assets.map((asset) => `<option value="${asset.id}">${escapeHtml(asset.name)} (${asset.type})</option>`).join("")}
        </select>
        <input name="duration_seconds" type="number" min="1" value="15" aria-label="Duration seconds">
        <button class="primary" type="submit">Add Item</button>
      </form>
      ${renderPlaylistItems(playlist)}
    </section>
  `).join("");
}

function renderPlaylistItems(playlist) {
  if (!playlist.items.length) return `<p class="muted">No playlist items yet.</p>`;
  return `
    <table class="table">
      <thead><tr><th>Pos</th><th>Asset</th><th>Duration</th><th>Enabled</th><th></th></tr></thead>
      <tbody>
        ${playlist.items.map((item) => `
          <tr>
            <td><input data-item-position="${playlist.id}:${item.id}" type="number" min="0" value="${item.position}"></td>
            <td>${escapeHtml(item.asset_name)}</td>
            <td><input data-item-duration="${playlist.id}:${item.id}" type="number" min="1" value="${item.duration_seconds}"></td>
            <td><input data-item-enabled="${playlist.id}:${item.id}" type="checkbox" ${item.enabled ? "checked" : ""}></td>
            <td><button class="danger" data-delete-item="${playlist.id}:${item.id}">Remove</button></td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
}

async function loadLogs() {
  const logs = await api("/api/logs");
  $("#log-list").innerHTML = logs.length ? `
    <table class="table">
      <thead><tr><th>Name</th><th>Size</th><th></th></tr></thead>
      <tbody>${logs.map((log) => `
        <tr><td>${escapeHtml(log.name)}</td><td>${bytes(log.size_bytes)}</td><td><a href="/api/logs/${encodeURIComponent(log.name)}/download">Download</a></td></tr>
      `).join("")}</tbody>
    </table>
  ` : `<p class="muted">No logs yet.</p>`;
}

document.addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) return;

  if (button.dataset.tab) setTab(button.dataset.tab);
  if (button.id === "refresh-status") await loadStatus();
  if (button.id === "refresh-assets") await loadAssets();
  if (button.id === "refresh-logs") await loadLogs();
  if (button.id === "open-player") window.open("/player", "_blank");
  if (button.id === "logout") {
    await api("/api/logout", { method: "POST" });
    showLogin();
  }
  if (button.id === "start-playback") {
    await api("/api/playback/start", { method: "POST" });
    await loadStatus();
  }
  if (button.id === "stop-playback") {
    await api("/api/playback/stop", { method: "POST" });
    await loadStatus();
  }
  if (button.id === "restart-player") {
    const result = await api("/api/system/restart-player", { method: "POST" });
    alert(result.message || "Restart requested");
  }
  if (button.dataset.editAsset) {
    const asset = state.assets.find((entry) => entry.id === button.dataset.editAsset);
    if (!asset) return;
    state.editingAssetId = asset.id;
    await loadAssets();
  }
  if (button.dataset.cancelAssetEdit) {
    state.editingAssetId = null;
    await loadAssets();
  }
  if (button.dataset.saveAsset) {
    const asset = state.assets.find((entry) => entry.id === button.dataset.saveAsset);
    const row = button.closest("[data-editing-asset]");
    if (!asset || !row) return;
    const payload = { name: row.querySelector("[data-asset-edit-name]").value.trim() };
    if (asset.type === "website") {
      payload.url = row.querySelector("[data-asset-edit-url]").value.trim();
      payload.display_mode = row.querySelector("[data-asset-edit-display-mode]").value;
    }
    await api(`/api/assets/${asset.id}`, { method: "PUT", body: JSON.stringify(payload) });
    state.editingAssetId = null;
    await Promise.all([loadAssets(), loadPlaylists(), loadStatus()]);
  }
  if (button.dataset.deleteAsset && confirm("Delete this asset?")) {
    await api(`/api/assets/${button.dataset.deleteAsset}`, { method: "DELETE" });
    await Promise.all([loadAssets(), loadPlaylists(), loadStatus()]);
  }
  if (button.dataset.activatePlaylist) {
    await api(`/api/playlists/${button.dataset.activatePlaylist}/activate`, { method: "POST" });
    await Promise.all([loadPlaylists(), loadStatus()]);
  }
  if (button.dataset.deletePlaylist && confirm("Delete this playlist?")) {
    await api(`/api/playlists/${button.dataset.deletePlaylist}`, { method: "DELETE" });
    await Promise.all([loadPlaylists(), loadStatus()]);
  }
  if (button.dataset.deleteItem) {
    const [playlistId, itemId] = button.dataset.deleteItem.split(":");
    await api(`/api/playlists/${playlistId}/items/${itemId}`, { method: "DELETE" });
    await loadPlaylists();
  }
});

document.addEventListener("change", async (event) => {
  const target = event.target;
  const key = target.dataset.itemDuration || target.dataset.itemPosition || target.dataset.itemEnabled;
  if (!key) return;
  const [playlistId, itemId] = key.split(":");
  const payload = {};
  if (target.dataset.itemDuration) payload.duration_seconds = Number(target.value);
  if (target.dataset.itemPosition) payload.position = Number(target.value);
  if (target.dataset.itemEnabled) payload.enabled = target.checked;
  await api(`/api/playlists/${playlistId}/items/${itemId}`, { method: "PUT", body: JSON.stringify(payload) });
  await loadPlaylists();
});

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("/api/login", {
      method: "POST",
      body: JSON.stringify({ username: $("#username").value, password: $("#password").value }),
    });
    await loadAll();
  } catch (error) {
    showLogin(error.message);
  }
});

$("#upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(event.target);
  await api("/api/assets/upload", { method: "POST", body: formData });
  event.target.reset();
  await Promise.all([loadAssets(), loadPlaylists(), loadStatus()]);
});

$("#link-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  await api("/api/assets/link", {
    method: "POST",
    body: JSON.stringify({ name: $("#link-name").value, url: $("#link-url").value, display_mode: "embed" }),
  });
  event.target.reset();
  await Promise.all([loadAssets(), loadPlaylists(), loadStatus()]);
});

$("#playlist-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  await api("/api/playlists", { method: "POST", body: JSON.stringify({ name: $("#playlist-name").value }) });
  event.target.reset();
  await Promise.all([loadPlaylists(), loadStatus()]);
});

$("#playlist-list").addEventListener("submit", async (event) => {
  const form = event.target.closest("[data-add-item]");
  if (!form) return;
  event.preventDefault();
  const formData = new FormData(form);
  await api(`/api/playlists/${form.dataset.addItem}/items`, {
    method: "POST",
    body: JSON.stringify({
      asset_id: formData.get("asset_id"),
      duration_seconds: Number(formData.get("duration_seconds")),
      enabled: true,
    }),
  });
  await loadPlaylists();
});

$("#settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  await api("/api/settings", {
    method: "PUT",
    body: JSON.stringify({
      player_name: $("#setting-player-name").value,
      max_upload_mb: Number($("#setting-max-upload").value),
    }),
  });
  await Promise.all([loadSettings(), loadStatus()]);
});

$("#password-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  await api("/api/settings/password", {
    method: "PUT",
    body: JSON.stringify({
      username: $("#setting-username").value,
      password: $("#setting-password").value,
    }),
  });
  $("#setting-password").value = "";
  alert("Login updated. Use the new credentials next time.");
});

api("/api/session").then(loadAll).catch(() => showLogin());
