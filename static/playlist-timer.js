(() => {
  function enhancePlaylistTimers() {
    const root = document.querySelector("#playlist-list");
    if (!root) return;

    root.querySelectorAll('form[data-add-item]').forEach((form) => {
      const input = form.querySelector('input[name="duration_seconds"]');
      if (!input || input.dataset.timerEnhanced === "1") return;

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
    });

    root.querySelectorAll("table.table").forEach((table) => {
      const headers = table.querySelectorAll("thead th");
      headers.forEach((header) => {
        if (header.textContent.trim() === "Duration") {
          header.textContent = "Display time (seconds)";
        }
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
