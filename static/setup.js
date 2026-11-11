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
    message("Setup saved. Restart the player to activate the new configuration. Your SSH connection will disconnect during reboot.");
    button.disabled = false;
    button.textContent = "Restart Player";
    button.type = "button";
    button.onclick = async () => {
      button.disabled = true;
      button.textContent = "Restarting...";
      try {
        const response = await fetch("/api/setup/reboot", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({token: data.reboot_token})
        });
        if (!response.ok) {
          const result = await response.json();
          throw new Error(result.detail || "Restart failed");
        }
        message("Restart requested. Reconnect to this player's management page after it boots.");
      } catch (error) {
        message("Restart request could not be confirmed: " + error.message + ". Check the player before retrying.", true);
        button.disabled = false;
        button.textContent = "Restart Player";
      }
    };
  } catch (e) { message(e.message, true); button.disabled = false; button.textContent = "Secure Player & Continue"; }
});
