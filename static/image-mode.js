(() => {
  const validModes = new Set(["fit", "fill", "stretch"]);

  function normalizeMode(value) {
    return validModes.has(value) ? value : "fit";
  }

  function titleCase(value) {
    return value.charAt(0).toUpperCase() + value.slice(1);
  }

  function enhanceAssetRows() {
    const list = document.querySelector("#asset-list");
    if (!list || typeof state === "undefined") return;

    for (const asset of state.assets) {
      if (asset.type !== "image") continue;
      const mode = normalizeMode(asset.display_mode);

      const editButton = list.querySelector(`button[data-edit-asset="${asset.id}"]`);
      if (editButton) {
        const row = editButton.closest("tr");
        const detailCell = row?.children?.[3];
        if (detailCell && !detailCell.querySelector(".image-mode-pill")) {
          detailCell.insertAdjacentHTML(
            "beforeend",
            `<br><span class="pill image-mode-pill">${titleCase(mode)}</span>`,
          );
        }
      }

      const saveButton = list.querySelector(`button[data-save-asset="${asset.id}"]`);
      if (saveButton) {
        const row = saveButton.closest("[data-editing-asset]");
        const detailCell = row?.children?.[3];
        if (detailCell && !detailCell.querySelector("[data-asset-edit-image-mode]")) {
          detailCell.insertAdjacentHTML(
            "beforeend",
            `<div class="form-row" style="margin-top:8px">
              <label>Display mode</label>
              <select data-asset-edit-image-mode aria-label="Image display mode">
                <option value="fit" ${mode === "fit" ? "selected" : ""}>Fit</option>
                <option value="fill" ${mode === "fill" ? "selected" : ""}>Fill</option>
                <option value="stretch" ${mode === "stretch" ? "selected" : ""}>Stretch</option>
              </select>
            </div>`,
          );
        }
      }
    }
  }

  const assetList = document.querySelector("#asset-list");
  if (assetList) {
    new MutationObserver(() => requestAnimationFrame(enhanceAssetRows))
      .observe(assetList, { childList: true, subtree: true });
  }

  document.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-save-asset]");
    if (!button || typeof state === "undefined") return;

    const asset = state.assets.find((entry) => entry.id === button.dataset.saveAsset);
    if (!asset || asset.type !== "image") return;

    event.preventDefault();
    event.stopImmediatePropagation();

    const row = button.closest("[data-editing-asset]");
    const nameInput = row?.querySelector("[data-asset-edit-name]");
    const modeSelect = row?.querySelector("[data-asset-edit-image-mode]");
    if (!row || !nameInput || !modeSelect) return;

    const response = await fetch(`/api/assets/${asset.id}/image-settings`, {
      method: "PUT",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: nameInput.value.trim(),
        display_mode: normalizeMode(modeSelect.value),
      }),
    });

    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      alert(data.detail || "Failed to save image display mode");
      return;
    }

    state.editingAssetId = null;
    await Promise.all([loadAssets(), loadPlaylists(), loadStatus()]);
  }, true);

  document.addEventListener("DOMContentLoaded", enhanceAssetRows);
  enhanceAssetRows();
})();
