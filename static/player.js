const stage = document.querySelector("#stage");
let playlistSignature = "";
let items = [];
let index = 0;
let timer = null;
let reloadTimer = null;
let directWindow = null;

function signature(data) {
  return JSON.stringify({
    state: data.state,
    playlist: data.playlist?.id,
    items: data.items.map((item) => [
      item.id,
      item.position,
      item.duration_seconds,
      item.enabled,
      item.asset_id,
      item.asset_url,
      item.asset_display_mode,
      item.asset_zoom_percent,
      item.asset_reload_seconds,
    ]),
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

function imageObjectFit(mode) {
  if (mode === "fill") return "cover";
  if (mode === "stretch") return "fill";
  return "contain";
}

function clearWebsiteReload() {
  if (reloadTimer) clearInterval(reloadTimer);
  reloadTimer = null;
}

function closeDirectWindow() {
  if (!directWindow) return;
  try {
    if (!directWindow.closed) directWindow.close();
  } catch (error) {
    console.warn("Unable to close direct website window", error);
  }
  directWindow = null;
  try {
    window.focus();
  } catch (_) {}
}

function applyEmbedZoom(iframe, zoomPercent) {
  const zoom = Math.min(200, Math.max(50, Number(zoomPercent || 100))) / 100;
  iframe.style.transformOrigin = "top left";
  iframe.style.transform = `scale(${zoom})`;
  iframe.style.width = `${100 / zoom}vw`;
  iframe.style.height = `${100 / zoom}vh`;
}

function playCurrent() {
  if (timer) clearTimeout(timer);
  clearWebsiteReload();
  closeDirectWindow();

  if (!items.length) {
    showMessage("No active playlist items");
    return;
  }

  const item = items[index % items.length];
  const durationMs = Math.max(1, item.duration_seconds) * 1000;
  const reloadSeconds = Math.max(0, Number(item.asset_reload_seconds || 0));

  if (item.asset_type === "image") {
    if (item.asset_file_present === false) {
      console.error("Skipping missing local asset", item.asset_id, item.asset_name);
      advanceSoon();
      return;
    }

    stage.innerHTML = `<img id="player-image" src="${item.media_url}" alt="${escapeHtml(item.asset_name)}">`;
    const image = document.querySelector("#player-image");
    image.style.objectFit = imageObjectFit(item.asset_display_mode);
    image.addEventListener("error", () => {
      console.error("Image failed to load", item.asset_id, item.asset_name);
      advanceSoon();
    }, { once: true });
  } else if (item.asset_type === "website") {
    if (item.asset_display_mode === "direct") {
      directWindow = window.open(item.asset_url, "pi-player-direct");
      if (!directWindow) {
        console.error("Direct website window was blocked", item.asset_url);
        showMessage("Direct website could not be opened");
        advanceSoon();
        return;
      }
      try {
        directWindow.focus();
      } catch (_) {}
      if (reloadSeconds > 0) {
        reloadTimer = setInterval(() => {
          try {
            if (directWindow && !directWindow.closed) directWindow.location.href = item.asset_url;
          } catch (error) {
            console.warn("Unable to reload direct website", error);
          }
        }, reloadSeconds * 1000);
      }
      timer = setTimeout(() => {
        clearWebsiteReload();
        closeDirectWindow();
        advance();
      }, durationMs);
      return;
    }

    stage.innerHTML = `<iframe id="player-web" src="${item.asset_url}" title="${escapeHtml(item.asset_name)}"></iframe>`;
    const iframe = document.querySelector("#player-web");
    applyEmbedZoom(iframe, item.asset_zoom_percent);
    if (reloadSeconds > 0) {
      reloadTimer = setInterval(() => {
        const current = document.querySelector("#player-web");
        if (current) current.src = item.asset_url;
      }, reloadSeconds * 1000);
    }
  } else {
    showMessage("Unsupported asset");
  }

  timer = setTimeout(advance, durationMs);
}

function advance() {
  index = (index + 1) % items.length;
  playCurrent();
}

function advanceSoon() {
  if (timer) clearTimeout(timer);
  clearWebsiteReload();
  timer = setTimeout(advance, 2000);
}

window.addEventListener("beforeunload", () => {
  clearWebsiteReload();
  closeDirectWindow();
});
setInterval(loadPlaylist, 5000);
loadPlaylist();
