/**
 * XHR/Fetch interceptor v2 — non-overridable fetch patch.
 *
 * Loaded via --init-script before any page scripts.
 * Uses Object.defineProperty with writable:false to prevent Zepto's
 * Grafana Faro telemetry wrapper from overwriting our patch.
 *
 * Captures responses from:
 * - Zepto BFF gateway: bff-gateway.zepto.com
 * - Instamart: /api/instamart/
 * - Blinkit: /v1/layout/search
 *
 * Captured responses stored in window.__xhrCaptures[] as {url, status, body, timestamp}.
 * Retrieve via browser_evaluate: () => JSON.stringify(window.__xhrCaptures)
 */
(function () {
  const _origFetch = window.fetch;
  window.__xhrCaptures = [];

  const patchedFetch = async function (...args) {
    const response = await _origFetch.apply(this, args);
    const url = typeof args[0] === 'string' ? args[0] : (args[0]?.url || '');

    if (
      url.includes('bff-gateway') ||
      url.includes('/api/instamart/') ||
      url.includes('/api/v1/search') ||
      url.includes('/api/v3/search') ||
      url.includes('/api/v4/catalog') ||
      url.includes('/v1/layout/search') ||
      url.includes('/cn/listings')
    ) {
      try {
        const clone = response.clone();
        const body = await clone.json();
        window.__xhrCaptures.push({
          url: url,
          status: response.status,
          body: body,
          timestamp: Date.now(),
        });
      } catch (e) {
        // Ignore parse errors for non-JSON responses
      }
    }
    return response;
  };

  // Make fetch non-writable AND non-configurable so Grafana Faro / other
  // telemetry wrappers cannot overwrite or redefine our patch.
  Object.defineProperty(window, 'fetch', {
    value: patchedFetch,
    writable: false,
    configurable: false,
  });
})();
