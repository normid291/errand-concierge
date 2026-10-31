/**
 * Runtime configuration.
 *
 * When the UI is served by the FastAPI backend, same-origin requests are used.
 * If you host the frontend separately (for example on Vercel) point this at the
 * backend, or set `window.ERRAND_CONCIERGE_API` before this file loads.
 */
(function () {
  var isStaticHost = /(^|\.)vercel\.app$/.test(window.location.hostname);
  var fallback = isStaticHost ? "https://errand-concierge-production.up.railway.app" : "";
  window.ERRAND_CONCIERGE_API = window.ERRAND_CONCIERGE_API || fallback;
})();
