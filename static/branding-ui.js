// v1 branding settings UI. Branding is management-surface only and never overlays playlist playback.
(() => {
  const $ = (selector) => document.querySelector(selector);

  function showMessage(text, isError = false) {
    const node = $("#branding-message");
    if (!node) return;
    node.textContent = text || "";
    node.classList.toggle("error", isError);
  }

  function renderLogo(data) {
    const configured = Boolean(data.logo_configured && data.logo_url);
    $("#branding-logo-status").textContent = configured ? "Configured" : "Not configured";
    const preview = $("#branding-logo-preview");
    const remove = $("#branding-logo-remove");
    if (preview) {
      preview.classList.toggle("hidden", !configured);
      if (configured) preview.src = `${data.logo_url}?v=${Date.now()}`;
      else preview.removeAttribute("src");
    }
    if (remove) remove.disabled = !configured;

    const topbarLogo = $("#topbar-brand-logo");
    if (topbarLogo) {
      topbarLogo.classList.toggle("hidden", !configured);
      if (configured) topbarLogo.src = `${data.logo_url}?v=${Date.now()}`;
      else topbarLogo.removeAttribute("src");
    }
  }

  function darkenHex(hex, amount = 0.22) {
    const value = String(hex || "").replace("#", "");
    if (!/^[0-9a-fA-F]{6}$/.test(value)) return "#174F4B";
    const channels = [0, 2, 4].map((offset) =>
      Math.max(0, Math.round(parseInt(value.slice(offset, offset + 2), 16) * (1 - amount)))
    );
    return `#${channels.map((channel) => channel.toString(16).padStart(2, "0")).join("")}`;
  }

  function applyBrandingTheme(data) {
    const primary = data.primary_color || "#226C67";
    const secondary = data.secondary_color || "#142422";
    const root = document.documentElement;

    root.style.setProperty("--accent", primary);
    root.style.setProperty("--accent-strong", darkenHex(primary));
    root.style.setProperty("--brand-secondary", secondary);
  }

  function syncColourPreset(colourSelector, presetSelector) {
    const colour = $(colourSelector);
    const preset = $(presetSelector);
    if (!colour || !preset) return;

    const value = colour.value.toUpperCase();
    const match = Array.from(preset.options).find(
      (option) => option.value && option.value.toUpperCase() === value
    );
    preset.value = match ? match.value : "";
  }

  function applyColourPreset(presetSelector, colourSelector, outputSelector) {
    const preset = $(presetSelector);
    const colour = $(colourSelector);
    const output = $(outputSelector);
    if (!preset || !colour || !preset.value) return;

    colour.value = preset.value;
    if (output) output.textContent = colour.value.toUpperCase();
  }

  function fillBranding(data) {
    applyBrandingTheme(data);
    $("#branding-product-name").value = data.product_name || "Pi Player";
    const topbarProductName = $("#topbar-product-name");
    if (topbarProductName) topbarProductName.textContent = data.product_name || "Pi Player";
    $("#branding-company-name").value = data.company_name || "";
    $("#branding-display-message").value = data.display_message || "";
    $("#branding-primary-color").value = data.primary_color || "#0F2F2B";
    $("#branding-secondary-color").value = data.secondary_color || "#7FAFA8";
    $("#branding-primary-color-value").textContent = $("#branding-primary-color").value.toUpperCase();
    $("#branding-secondary-color-value").textContent = $("#branding-secondary-color").value.toUpperCase();
    syncColourPreset("#branding-primary-color", "#branding-primary-preset");
    syncColourPreset("#branding-secondary-color", "#branding-secondary-preset");
    $("#branding-support-name").value = data.support_name || "";
    $("#branding-support-email").value = data.support_email || "";
    $("#branding-support-url").value = data.support_url || "";
    $("#branding-footer-text").value = data.footer_text || "";
    $("#branding-show-powered-by").checked = data.show_powered_by !== false;
    renderLogo(data);
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
      display_message: $("#branding-display-message").value.trim(),
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

  async function uploadLogo() {
    const input = $("#branding-logo-file");
    const file = input?.files?.[0];
    if (!file) {
      showMessage("Choose a logo file first.", true);
      return;
    }
    if (file.size > 2 * 1024 * 1024) {
      showMessage("Logo must be 2 MB or smaller.", true);
      return;
    }

    const data = new FormData();
    data.append("file", file);
    showMessage("Uploading logo...");
    try {
      const response = await fetch("/api/branding/logo", {
        method: "POST",
        credentials: "same-origin",
        body: data,
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "Unable to upload logo");
      input.value = "";
      const fileName = $("#branding-logo-file-name");
      if (fileName) fileName.textContent = "No file selected";
      fillBranding(result);
      showMessage("Logo uploaded.");
    } catch (error) {
      showMessage(error.message, true);
    }
  }

  async function removeLogo() {
    if (!confirm("Remove the configured branding logo?")) return;
    showMessage("Removing logo...");
    try {
      const response = await fetch("/api/branding/logo", {
        method: "DELETE",
        credentials: "same-origin",
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "Unable to remove logo");
      fillBranding(result);
      showMessage("Logo removed.");
    } catch (error) {
      showMessage(error.message, true);
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    const form = $("#branding-form");
    if (!form) return;
    form.addEventListener("submit", saveBranding);
    $("#branding-logo-upload")?.addEventListener("click", uploadLogo);
    $("#branding-logo-remove")?.addEventListener("click", removeLogo);

    $("#branding-logo-file")?.addEventListener("change", (event) => {
      const fileName = $("#branding-logo-file-name");
      if (fileName) fileName.textContent = event.target.files?.[0]?.name || "No file selected";
    });

    $(".branding-file-button")?.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        $("#branding-logo-file")?.click();
      }
    });

    $("#branding-primary-preset")?.addEventListener("change", () => {
      applyColourPreset(
        "#branding-primary-preset",
        "#branding-primary-color",
        "#branding-primary-color-value"
      );
    });
    $("#branding-secondary-preset")?.addEventListener("change", () => {
      applyColourPreset(
        "#branding-secondary-preset",
        "#branding-secondary-color",
        "#branding-secondary-color-value"
      );
    });

    $("#branding-primary-color")?.addEventListener("input", (event) => {
      $("#branding-primary-color-value").textContent = event.target.value.toUpperCase();
      syncColourPreset("#branding-primary-color", "#branding-primary-preset");
    });
    $("#branding-secondary-color")?.addEventListener("input", (event) => {
      $("#branding-secondary-color-value").textContent = event.target.value.toUpperCase();
      syncColourPreset("#branding-secondary-color", "#branding-secondary-preset");
    });

    loadBranding();
  });
})();
