const stage = document.querySelector("#stage");
let playlistSignature = "";
let items = [];
let index = 0;
let timer = null;

function signature(data) {
  return JSON.stringify({
    state: data.state,
    playlist: data.playlist?.id,
    items: data.items.map((item) => [item.id, item.position, item.duration_seconds, item.enabled, item.asset_id, item.asset_url, item.asset_display_mode]),
  });
}

async function loadPlaylist() {
  try {
    const response = await fetch("/api/player/playlist", { cache: "no-store" });
    const data = await response.json();
    const nextSignature = signature(data);
    if (nextSignature !== playlistSignature) {
      playlistSignature = nextSignature;
      items = data.state === "playing" ? data.items.filter((item) => item.enabled) : [];
      index = 0;
      playCurrent();
    }
  } catch (error) {
    showMessage("Unable to load playlist");
  }
}

function showMessage(message) {
  stage.innerHTML = `<div class="player-message">${escapeHtml(message)}</div>`;
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

function playCurrent() {
  if (timer) clearTimeout(timer);
  if (!items.length) {
    showMessage("No active playlist items");
    return;
  }
  const item = items[index % items.length];
  if (item.asset_type === "image") {
    if (item.asset_file_present === false) {
      console.error("Skipping missing local asset", item.asset_id, item.asset_name);
      advanceSoon();
      return;
    }
    stage.innerHTML = `<img id="player-image" src="${item.media_url}" alt="${escapeHtml(item.asset_name)}">`;
    const image = document.querySelector("#player-image");
    image.addEventListener("error", () => {
      console.error("Image failed to load", item.asset_id, item.asset_name);
      advanceSoon();
    }, { once: true });
  } else if (item.asset_type === "website") {
    if (item.asset_display_mode === "direct") {
      showMessage(`Opening ${item.asset_name}...`);
      window.location.replace(item.asset_url);
      return;
    }
    stage.innerHTML = `<iframe src="${item.asset_url}" title="${escapeHtml(item.asset_name)}"></iframe>`;
  } else {
    showMessage("Unsupported asset");
  }
  timer = setTimeout(advance, Math.max(1, item.duration_seconds) * 1000);
}

function advance() {
  index = (index + 1) % items.length;
  playCurrent();
}

function advanceSoon() {
  if (timer) clearTimeout(timer);
  timer = setTimeout(advance, 2000);
}

setInterval(loadPlaylist, 5000);
loadPlaylist();
