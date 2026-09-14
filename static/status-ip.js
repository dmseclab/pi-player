(() => {
  function isLoopback(value) {
    return value === "localhost" || value === "::1" || /^127\./.test(value);
  }

  function preferredAddress() {
    const host = window.location.hostname;
    return host && !isLoopback(host) ? host : null;
  }

  function fixStatusAddress() {
    const status = document.querySelector("#status-content");
    const preferred = preferredAddress();
    if (!status || !preferred) return;

    for (const block of status.children) {
      const label = block.querySelector("strong")?.textContent?.trim();
      if (label !== "IP addresses") continue;
      const value = block.querySelector(".muted");
      if (value && value.textContent.trim() !== preferred) value.textContent = preferred;
    }
  }

  const status = document.querySelector("#status-content");
  if (status) {
    new MutationObserver(() => requestAnimationFrame(fixStatusAddress))
      .observe(status, { childList: true });
  }
  document.addEventListener("DOMContentLoaded", fixStatusAddress);
  fixStatusAddress();
})();
