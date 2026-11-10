const $ = (s) => document.querySelector(s);
const message = (text, error=false) => { $("#setup-message").innerHTML = `<div class="message ${error ? "error" : "success"}">${text}</div>`; };

(async () => {
  try {
    const r = await fetch("/api/setup/status", {cache:"no-store"});
    const s = await r.json();
    if (!s.setup_required) window.location.replace("/");
    if (s.hostname) $("#hostname").value = s.hostname === "localhost" ? "pi-player" : s.hostname;
    if (s.ntp_server) $("#ntp-server").value = s.ntp_server;
  } catch (_) { message("Unable to read player setup status.", true); }
})();

const supportToggle = $("#create-support-user");
const supportFields = $("#support-fields");
const updateSupportFields = () => {
  supportFields.hidden = !supportToggle.checked;
  $("#support-username").required = supportToggle.checked;
  $("#support-password").required = supportToggle.checked;
};
supportToggle.addEventListener("change", updateSupportFields);
updateSupportFields();

$("#setup-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.submitter; button.disabled = true; button.textContent = "Applying...";
  const payload = {
    bootstrap_username: $("#bootstrap-username").value.trim(), bootstrap_password: $("#bootstrap-password").value,
    admin_username: $("#admin-username").value.trim(), admin_password: $("#admin-password").value,
    create_support_user: supportToggle.checked,
    support_username: supportToggle.checked ? $("#support-username").value.trim() : null,
    support_password: supportToggle.checked ? $("#support-password").value : null,
    hostname: $("#hostname").value.trim(),
    ntp_server: $("#ntp-server").value.trim() || null
  };
  try {
    const r = await fetch("/api/setup/complete", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload)});
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || "Setup failed");
    message("Setup complete. Opening the admin login...");
    setTimeout(() => window.location.replace("/"), 1200);
  } catch (e) { message(e.message, true); button.disabled = false; button.textContent = "Secure Player & Continue"; }
});
