// Local, pinned PDF.js: playback never depends on an Internet connection.
let pdfLibrary;
function startPdfPlayback(item, stage, onReady, onError) {
  let stopped = false;
  let loadingTask;
  let renderTask;
  let pageTimer;
  let watchdog = setTimeout(() => fail(new Error("PDF loading timed out")), 30000);
  const alive = () => !stopped;
  function fail(error) {
    if (!alive()) return;
    clearTimeout(watchdog);
    onError(error);
  }
  async function run() {
    try {
      pdfLibrary ||= import("/static/vendor/pdfjs/legacy/build/pdf.mjs");
      const pdfjs = await pdfLibrary;
      if (!alive()) return;
      pdfjs.GlobalWorkerOptions.workerSrc = "/static/vendor/pdfjs/legacy/build/pdf.worker.mjs";
      loadingTask = pdfjs.getDocument({
        url: item.media_url,
        cMapUrl: "/static/vendor/pdfjs/cmaps/", cMapPacked: true,
        standardFontDataUrl: "/static/vendor/pdfjs/standard_fonts/",
        wasmUrl: "/static/vendor/pdfjs/wasm/",
        isEvalSupported: false,
      });
      loadingTask.onPassword = () => fail(new Error("Password protected PDFs are unsupported"));
      const pdf = await loadingTask.promise;
      if (!alive()) return;
      let pageNumber = 1;
      async function renderPage() {
        try {
          const page = await pdf.getPage(pageNumber);
          if (!alive()) return;
          const viewport = page.getViewport({ scale: 1 });
          const scale = Math.min(stage.clientWidth / viewport.width, stage.clientHeight / viewport.height);
          const fitted = page.getViewport({ scale });
          // Bound memory on Pi displays, including 4K screens.
          const pixelRatio = Math.min(window.devicePixelRatio || 1, 2,
            Math.sqrt(8000000 / (fitted.width * fitted.height)));
          const canvas = document.createElement("canvas");
          canvas.width = Math.max(1, Math.floor(fitted.width * pixelRatio));
          canvas.height = Math.max(1, Math.floor(fitted.height * pixelRatio));
          canvas.style.width = `${fitted.width}px`;
          canvas.style.height = `${fitted.height}px`;
          renderTask = page.render({ canvasContext: canvas.getContext("2d"), viewport: fitted,
            transform: [pixelRatio, 0, 0, pixelRatio, 0, 0] });
          await renderTask.promise;
          if (!alive()) return;
          stage.replaceChildren(canvas);
          page.cleanup();
          if (pageNumber === 1 && watchdog) {
            clearTimeout(watchdog); watchdog = null;
            onReady();
          }
          pageNumber = pageNumber % pdf.numPages + 1;
          pageTimer = setTimeout(renderPage, Math.max(1, Number(item.asset_pdf_page_seconds || 10)) * 1000);
        } catch (error) { fail(error); }
      }
      await renderPage();
    } catch (error) { fail(error); }
  }
  run();
  return () => {
    stopped = true;
    clearTimeout(pageTimer); clearTimeout(watchdog);
    renderTask?.cancel();
    loadingTask?.destroy().catch(() => {});
  };
}
