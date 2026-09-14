// Capture the link form submission before the legacy handler so the selected
// display mode is honored at creation time. The existing edit flow remains.
document.querySelector("#link-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  event.stopImmediatePropagation();

  const form = event.currentTarget;
  await api("/api/assets/link", {
    method: "POST",
    body: JSON.stringify({
      name: document.querySelector("#link-name").value,
      url: document.querySelector("#link-url").value,
      display_mode: document.querySelector("#link-display-mode").value,
    }),
  });

  form.reset();
  await Promise.all([loadAssets(), loadPlaylists(), loadStatus()]);
}, true);
