/**
 * XHR/Fetch interceptor init script for Playwright MCP.
 * Loaded via --init-script before any page scripts.
 *
 * Patches window.fetch to capture API responses from:
 * - Zepto: /api/ endpoints (search, catalog)
 * - Instamart: /api/instamart/ endpoints (search, category)
 * - Blinkit: /v1/layout/search
 *
 * Captured responses stored in window.__xhrCaptures[] as {url, status, body}.
 * Retrieve via browser_evaluate: () => JSON.stringify(window.__xhrCaptures)
 */
(function () {
  window.__xhrCaptures = [];
  const _origFetch = window.fetch;

  window.fetch = async function (...args) {
    const response = await _origFetch.apply(this, args);
    const url = typeof args[0] === 'string' ? args[0] : args[0]?.url || '';

    // Capture API responses we care about
    if (
      url.includes('/api/instamart/search') ||
      url.includes('/api/instamart/category') ||
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
})();
