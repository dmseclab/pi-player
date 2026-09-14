const assetFileInput = document.querySelector("#asset-file");
const assetFileName = document.querySelector("#asset-file-name");
const uploadForm = document.querySelector("#upload-form");

function updateFileName() {
  if (!assetFileInput || !assetFileName) return;
  assetFileName.textContent = assetFileInput.files?.[0]?.name || "No file chosen";
}

assetFileInput?.addEventListener("change", updateFileName);
uploadForm?.addEventListener("reset", () => {
  setTimeout(updateFileName, 0);
});
