(() => {
  function selectedAssetIsVideo(select) {
    if (!select || !select.value) return false;
    const option = select.options[select.selectedIndex];
    if (option?.dataset?.assetType) return option.dataset.assetType === "video";
    if (/\(video\)\s*$/i.test(option?.textContent?.trim() || "")) return true;
    try {
      const asset = state.assets.find((entry) => entry.id === select.value);
      return asset?.type === "video";
    } catch (_) {
      return false;
    }
  }

  function syncTimer(form) {
    const select = form.querySelector('select[name="asset_id"]');
    const input = form.querySelector('input[name="duration_seconds"]');
    if (!select || !input) return;

    const isVideo = selectedAssetIsVideo(select);
    const wrapper = input.closest('.playlist-timer-field');
    const label = wrapper?.querySelector('label');
    let hidden = form.querySelector('input[data-video-auto-duration]');

    if (isVideo) {
      if (!input.dataset.previousValue) input.dataset.previousValue = input.value || "15";
      input.disabled = true;
      input.required = false;
      input.value = "";
      input.placeholder = "Auto";
      input.setAttribute("aria-label", "Automatic video display time");
      input.setAttribute("title", "Automatic: video plays to its natural end");
      if (label) label.textContent = "Display time — Auto (video length)";

      // The API still requires a duration value in the playlist item schema.
      // Keep that compatibility value out of the UI; normal non-looping video
      // playback advances on the video's ended event instead of this number.
      if (!hidden) {
        hidden = document.createElement("input");
        hidden.type = "hidden";
        hidden.name = "duration_seconds";
        hidden.dataset.videoAutoDuration = "1";
        hidden.value = "15";
        form.appendChild(hidden);
      }
    } else {
      input.disabled = false;
      input.required = true;
      if (!input.value) input.value = input.dataset.previousValue || "15";
      input.placeholder = "";
      input.setAttribute("aria-label", "Display time in seconds");
      input.setAttribute("title", "How long this slide should stay on screen");
      if (label) label.textContent = "Display time (seconds)";
      hidden?.remove();
    }
  }

  function enhancePlaylistTimers() {
    const root = document.querySelector("#playlist-list");
    if (!root) return;

    root.querySelectorAll('form[data-add-item]').forEach((form) => {
      const input = form.querySelector('input[name="duration_seconds"]');
      const select = form.querySelector('select[name="asset_id"]');
      if (!input || !select) return;

      if (input.dataset.timerEnhanced !== "1") {
        input.dataset.timerEnhanced = "1";
        input.setAttribute("aria-label", "Display time in seconds");
        input.setAttribute("title", "How long this slide should stay on screen");

        const wrapper = document.createElement("div");
        wrapper.className = "form-row compact-form-row playlist-timer-field";
        const label = document.createElement("label");
        label.textContent = "Display time (seconds)";
        input.parentNode.insertBefore(wrapper, input);
        wrapper.appendChild(label);
        wrapper.appendChild(input);
      }

      if (select.dataset.autoTimerBound !== "1") {
        select.dataset.autoTimerBound = "1";
        select.addEventListener("change", () => syncTimer(form));
      }
      syncTimer(form);
    });

    root.querySelectorAll("table.table").forEach((table) => {
      const headers = table.querySelectorAll("thead th");
      headers.forEach((header) => {
        if (header.textContent.trim() === "Duration") header.textContent = "Display time";
      });
      table.querySelectorAll("input[data-item-duration]").forEach((input) => {
        input.setAttribute("aria-label", "Display time in seconds");
        input.setAttribute("title", "How long this slide should stay on screen");
      });
    });
  }

  const root = document.querySelector("#playlist-list");
  if (root) {
    new MutationObserver(() => requestAnimationFrame(enhancePlaylistTimers))
      .observe(root, { childList: true, subtree: true });
  }
  document.addEventListener("DOMContentLoaded", enhancePlaylistTimers);
  enhancePlaylistTimers();
})();
