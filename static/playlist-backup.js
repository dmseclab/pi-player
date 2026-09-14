(() => {
  function enhancePlaylistBackup() {
    const root = document.querySelector("#playlist-list");
    if (!root) return;

    const panel = root.closest(".panel");
    const playlistForm = panel?.querySelector("#playlist-form");
    if (panel && playlistForm && !panel.querySelector(".playlist-backup-toolbar")) {
      const toolbar = document.createElement("div");
      toolbar.className = "toolbar playlist-backup-toolbar";
      toolbar.innerHTML = `
        <button type="button" data-import-playlist-package>Import Playlist Package</button>
        <input type="file" accept=".zip,application/zip" data-playlist-package-file hidden>
        <span class="muted">Restores playlist items, display times, links and local images.</span>
      `;
      playlistForm.insertAdjacentElement("afterend", toolbar);
    }

    root.querySelectorAll("section.panel").forEach((section) => {
      const activate = section.querySelector("button[data-activate-playlist]");
      if (!activate) return;
      const playlistId = activate.dataset.activatePlaylist;
      const toolbar = activate.closest(".toolbar");
      if (!toolbar || toolbar.querySelector("[data-export-playlist]")) return;

      const button = document.createElement("button");
      button.type = "button";
      button.dataset.exportPlaylist = playlistId;
      button.textContent = "Export";

      const deleteButton = toolbar.querySelector("button[data-delete-playlist]");
      if (deleteButton) {
        toolbar.insertBefore(button, deleteButton);
      } else {
        toolbar.appendChild(button);
      }
    });
  }

  const root = document.querySelector("#playlist-list");
  if (root) {
    new MutationObserver(() => requestAnimationFrame(enhancePlaylistBackup))
      .observe(root, { childList: true, subtree: true });
  }

  document.addEventListener("click", (event) => {
    const exportButton = event.target.closest("button[data-export-playlist]");
    if (exportButton) {
      window.location.href = `/api/playlists/${encodeURIComponent(exportButton.dataset.exportPlaylist)}/export`;
      return;
    }

    const importButton = event.target.closest("button[data-import-playlist-package]");
    if (importButton) {
      document.querySelector("[data-playlist-package-file]")?.click();
    }
  });

  document.addEventListener("change", async (event) => {
    const input = event.target.closest("[data-playlist-package-file]");
    if (!input || !input.files?.length) return;

    const file = input.files[0];
    const formData = new FormData();
    formData.append("file", file);
    input.disabled = true;

    try {
      const result = await api("/api/playlists/import", {
        method: "POST",
        body: formData,
      });
      alert(`Playlist '${result.playlist_name}' imported successfully. Review it, then Activate when ready.`);
      await Promise.all([loadAssets(), loadPlaylists(), loadStatus()]);
    } catch (error) {
      alert(error.message || "Playlist import failed");
    } finally {
      input.value = "";
      input.disabled = false;
    }
  });

  document.addEventListener("DOMContentLoaded", enhancePlaylistBackup);
  enhancePlaylistBackup();
})();
