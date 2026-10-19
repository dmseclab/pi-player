// v1 branding settings UI. Branding is management-surface only and never overlays playlist playback.
(() => {
  const $ = (selector) => document.querySelector(selector);

  function showMessage(text, isError = false) {
    const node = $("#branding-message");
    if (!node) return;
    node.textContent = text || "";
    node.classList.toggle("error", isError);
  }

  function fillBranding(data) {
    $("#branding-product-name").value = data.product_name || "Pi Player";
    $("#branding-company-name").value = data.company_name || "";
    $("#branding-primary-color").value = data.primary_color || "#0F2F2B";
    $("#branding-secondary-color").value = data.secondary_color || "#7FAFA8";
    $("#branding-support-name").value = data.support_name || "";
    $("#branding-support-email").value = data.support_email || "";
    $("#branding-support-url").value = data.support_url || "";
    $("#branding-footer-text").value = data.footer_text || "";
    $("#branding-show-powered-by").checked = data.show_powered_by !== false;
    $("#branding-logo-status").textContent = data.logo_configured ? "Configured" : "Not configured";
  }

  async function loadBranding() {
    try {
      const response = await fetch("/api/branding", { credentials: "same-origin" });
      if (!response.ok) throw new Error("Unable to load branding settings");
      fillBranding(await response.json());
    } catch (error) {
      showMessage(error.message, true);
    }
  }

  async function saveBranding(event) {
    event.preventDefault();
    showMessage("Saving...");
    const payload = {
      product_name: $("#branding-product-name").value.trim(),
      company_name: $("#branding-company-name").value.trim(),
      primary_color: $("#branding-primary-color").value.toUpperCase(),
      secondary_color: $("#branding-secondary-color").value.toUpperCase(),
      support_name: $("#branding-support-name").value.trim(),
      support_email: $("#branding-support-email").value.trim(),
      support_url: $("#branding-support-url").value.trim(),
      footer_text: $("#branding-footer-text").value.trim(),
      show_powered_by: $("#branding-show-powered-by").checked,
    };

    try {
      const response = await fetch("/api/branding", {
        method: "PUT",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Unable to save branding settings");
      fillBranding(data);
      showMessage("Branding settings saved.");
    } catch (error) {
      showMessage(error.message, true);
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    const form = $("#branding-form");
    if (!form) return;
    form.addEventListener("submit", saveBranding);
    loadBranding();
  });
})();
