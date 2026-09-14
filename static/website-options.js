(() => {
  const reloadOptions = [
    [0, "Every slide"],
    [300, "Every 5 minutes"],
    [900, "Every 15 minutes"],
    [1800, "Every 30 minutes"],
  ];

  function reloadOptionsHtml(selected) {
    const current = Number(selected || 0);
    return reloadOptions.map(([value, label]) =>
      `<option value="${value}" ${current === value ? "selected" : ""}>${label}</option>`
    ).join("");
  }

  function addCreationControls() {
    const form = document.querySelector("#link-form");
    const actions = form?.querySelector(".asset-actions");
    if (!form || !actions || form.querySelector("#link-zoom-percent")) return;

    actions.insertAdjacentHTML("afterbegin", `
      <div class="form-row compact-form-row website-option-field">
        <label for="link-zoom-percent">Zoom</label>
        <select id="link-zoom-percent">
          <option value="50">50%</option>
          <option value="75">75%</option>
          <option value="90">90%</option>
          <option value="100" selected>100%</option>
          <option value="110">110%</option>
          <option value="125">125%</option>
          <option value="150">150%</option>
          <option value="175">175%</option>
          <option value="200">200%</option>
        </select>
      </div>
      <div class="form-row compact-form-row website-option-field">
        <label for="link-reload-seconds">Page reload</label>
        <select id="link-reload-seconds">${reloadOptionsHtml(0)}</select>
      </div>
      <button type="button" id="test-link">Test Link</button>
    `);
  }

  function enhanceEditRows() {
    if (typeof state === "undefined") return;
    const root = document.querySelector("#asset-list");
    if (!root) return;

    for (const asset of state.assets) {
      if (asset.type !== "website") continue;
      const saveButton = root.querySelector(`button[data-save-asset="${asset.id}"]`);
      if (!saveButton) continue;
      const row = saveButton.closest("[data-editing-asset]");
      const detail = row?.children?.[3];
      if (!detail || detail.querySelector("[data-website-options]")) continue;

      const zoom = Number(asset.zoom_percent || 100);
      detail.insertAdjacentHTML("beforeend", `
        <div data-website-options class="website-edit-options">
          <div class="form-row compact-form-row">
            <label>Zoom</label>
            <select data-asset-edit-zoom>
              ${[50,75,90,100,110,125,150,175,200].map((value) => `<option value="${value}" ${zoom === value ? "selected" : ""}>${value}%</option>`).join("")}
            </select>
          </div>
          <div class="form-row compact-form-row">
            <label>Page reload</label>
            <select data-asset-edit-reload>${reloadOptionsHtml(asset.reload_seconds)}</select>
          </div>
          <button type="button" data-test-asset-link="${asset.id}">Test Link</button>
          <div class="muted website-option-note">Zoom applies to Embed mode. Direct websites use Chromium's normal 100% page zoom.</div>
        </div>
      `);
    }
  }

  function openTest(url) {
    const clean = (url || "").trim();
    if (!clean) {
      alert("Enter a website URL first.");
      return;
    }
    window.open(clean, "_blank", "noopener");
  }

  document.addEventListener("click", async (event) => {
    if (event.target.closest("#test-link")) {
      openTest(document.querySelector("#link-url")?.value);
      return;
    }

    const testAsset = event.target.closest("[data-test-asset-link]");
    if (testAsset && typeof state !== "undefined") {
      const asset = state.assets.find((entry) => entry.id === testAsset.dataset.testAssetLink);
      openTest(asset?.url);
      return;
    }

    const saveButton = event.target.closest("button[data-save-asset]");
    if (!saveButton || typeof state === "undefined") return;
    const asset = state.assets.find((entry) => entry.id === saveButton.dataset.saveAsset);
    if (!asset || asset.type !== "website") return;

    event.preventDefault();
    event.stopImmediatePropagation();

    const row = saveButton.closest("[data-editing-asset]");
    const name = row?.querySelector("[data-asset-edit-name]")?.value.trim();
    const url = row?.querySelector("[data-asset-edit-url]")?.value.trim();
    const mode = row?.querySelector("[data-asset-edit-display-mode]")?.value;
    const zoom = Number(row?.querySelector("[data-asset-edit-zoom]")?.value || 100);
    const reload = Number(row?.querySelector("[data-asset-edit-reload]")?.value || 0);

    await api(`/api/assets/${asset.id}/website-settings`, {
      method: "PUT",
      body: JSON.stringify({
        name,
        url,
        display_mode: mode,
        zoom_percent: zoom,
        reload_seconds: reload,
      }),
    });
    state.editingAssetId = null;
    await Promise.all([loadAssets(), loadPlaylists(), loadStatus()]);
  }, true);

  const assetList = document.querySelector("#asset-list");
  if (assetList) {
    new MutationObserver(() => requestAnimationFrame(enhanceEditRows))
      .observe(assetList, { childList: true, subtree: true });
  }

  document.addEventListener("DOMContentLoaded", () => {
    addCreationControls();
    enhanceEditRows();
  });
  addCreationControls();
  enhanceEditRows();
})();
