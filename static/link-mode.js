// Capture the link form submission before the legacy handler so website
// display options are honored at creation time.
document.querySelector("#link-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  event.stopImmediatePropagation();

  const form = event.currentTarget;
  const created = await api("/api/assets/link", {
    method: "POST",
    body: JSON.stringify({
      name: document.querySelector("#link-name").value,
      url: document.querySelector("#link-url").value,
      display_mode: document.querySelector("#link-display-mode").value,
    }),
  });

  await api(`/api/assets/${created.id}/website-settings`, {
    method: "PUT",
    body: JSON.stringify({
      name: created.name,
      url: created.url,
      display_mode: created.display_mode || "embed",
      zoom_percent: Number(document.querySelector("#link-zoom-percent")?.value || 100),
      reload_seconds: Number(document.querySelector("#link-reload-seconds")?.value || 0),
    }),
  });

  form.reset();
  if (document.querySelector("#link-zoom-percent")) document.querySelector("#link-zoom-percent").value = "100";
  if (document.querySelector("#link-reload-seconds")) document.querySelector("#link-reload-seconds").value = "0";
  await Promise.all([loadAssets(), loadPlaylists(), loadStatus()]);
}, true);
