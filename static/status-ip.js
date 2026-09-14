(() => {
  function isLoopback(value) {
    return value === "127.0.0.1" || value === "::1" || value === "localhost";
  }

  function preferredAddress() {
    const host = window.location.hostname;
    return host && !isLoopback(host) ? host : null;
  }

  function fixStatusAddress() {
    const status = document.querySelector("#status-content");
    if (!status) return;
    const preferred = preferredAddress();
    if (!preferred) return;

    for (const block of status.children) {
      const label = block.querySelector("strong")?.textContent?.trim();
      if (label !== "IP addresses") continue;
      const value = block.querySelector(".muted");
      if (!value) continue;
      const current = value.textContent.split(",").map((item) => item.trim()).filter(Boolean);
      const nonLoopback = current.filter((item) => !isLoopback(item));
      value.textContent = nonLoopback.length ? nonLoopback.join(", ") : preferred;
    }
  }

  const observer = new MutationObserver(fixStatusAddress);
  const status = document.querySelector("#status-content");
  if (status) observer.observe(status, { childList: true, subtree: true });
  document.addEventListener("DOMContentLoaded", fixStatusAddress);
  fixStatusAddress();
})();
