const assetFileInput = document.querySelector("#asset-file");
const assetFileName = document.querySelector("#asset-file-name");
const uploadForm = document.querySelector("#upload-form");

function updateFileName() {
  if (!assetFileInput || !assetFileName) return;
  assetFileName.textContent = assetFileInput.files?.[0]?.name || "No file chosen";
}

function uploadBytes(value) {
  if (!Number.isFinite(value)) return "";
  const units = ["B", "KB", "MB", "GB"];
  let size = value;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(index ? 1 : 0)} ${units[index]}`;
}

function ensureUploadProgress() {
  if (!uploadForm) return null;
  let box = uploadForm.querySelector(".upload-progress-box");
  if (!box) {
    box = document.createElement("div");
    box.className = "upload-progress-box hidden";
    box.innerHTML = '<div class="upload-progress-track"><div class="upload-progress-bar"></div></div><div class="upload-progress-text muted">Preparing upload...</div>';
    uploadForm.querySelector(".asset-actions")?.insertAdjacentElement("afterend", box);
  }
  return box;
}

function isVideoUpload(file) {
  return !!file && /\.(mp4|webm)$/i.test(file.name);
}

assetFileInput?.addEventListener("change", updateFileName);
uploadForm?.addEventListener("reset", () => setTimeout(updateFileName, 0));
ensureUploadProgress();

// This capture-phase handler is the single owner of asset uploads. admin.js still
// contains the legacy fetch submit handler for compatibility, but it is prevented
// from running here so every image/video upload uses XHR progress reporting.
uploadForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  event.stopImmediatePropagation();

  const file = assetFileInput?.files?.[0];
  if (!file) return;

  const data = new FormData(uploadForm);
  if (isVideoUpload(file)) {
    data.set("video_muted", String(!!uploadForm.querySelector("[data-upload-video-muted]")?.checked));
    data.set("video_loop", String(!!uploadForm.querySelector("[data-upload-video-loop]")?.checked));
  }

  const box = ensureUploadProgress();
  const bar = box.querySelector(".upload-progress-bar");
  const text = box.querySelector(".upload-progress-text");
  const button = uploadForm.querySelector('button[type="submit"]');
  box.classList.remove("hidden");
  bar.style.width = "0%";
  text.className = "upload-progress-text muted";
  text.textContent = `Uploading ${file.name} — 0%`;
  button.disabled = true;

  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/assets/upload");
  xhr.withCredentials = true;

  xhr.upload.addEventListener("progress", (progressEvent) => {
    if (!progressEvent.lengthComputable) return;
    const percent = Math.min(100, Math.round((progressEvent.loaded / progressEvent.total) * 100));
    bar.style.width = `${percent}%`;
    text.textContent = `Uploading ${file.name} — ${percent}% (${uploadBytes(progressEvent.loaded)} / ${uploadBytes(progressEvent.total)})`;
  });

  const fail = (message) => {
    button.disabled = false;
    bar.style.width = "0%";
    text.className = "upload-progress-text upload-error";
    text.textContent = message;
  };

  xhr.addEventListener("error", () => fail("Upload failed: network or connection error."));
  xhr.addEventListener("abort", () => fail("Upload cancelled."));
  xhr.addEventListener("load", async () => {
    let payload = {};
    try { payload = JSON.parse(xhr.responseText || "{}"); } catch (_) {}
    if (xhr.status < 200 || xhr.status >= 300) {
      fail(`Upload failed: ${payload.detail || `HTTP ${xhr.status}`}`);
      return;
    }

    bar.style.width = "100%";
    text.className = "upload-progress-text upload-success";
    text.textContent = `Upload complete: ${file.name}`;
    button.disabled = false;
    uploadForm.reset();
    try {
      if (typeof loadAssets === "function" && typeof loadPlaylists === "function" && typeof loadStatus === "function") {
        await Promise.all([loadAssets(), loadPlaylists(), loadStatus()]);
      }
    } catch (error) {
      console.error("Upload completed but UI refresh failed", error);
    }
  });

  xhr.send(data);
}, true);
