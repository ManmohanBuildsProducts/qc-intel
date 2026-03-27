/**
 * Playwright MCP stealth init script.
 *
 * Loaded via --init-script before any page scripts run.
 * Patches common bot-detection signals used by Cloudflare, Akamai,
 * AWS WAF, and DataDome.
 *
 * Based on puppeteer-extra-plugin-stealth evasions (pre-abandonment)
 * and playwright-stealth patches, updated for 2025-2026 detection.
 */

// 1. navigator.webdriver — the #1 headless detection signal
Object.defineProperty(navigator, 'webdriver', {
  get: () => undefined,
  configurable: true,
});

// 2. Chrome runtime — headless Chrome may lack window.chrome or chrome.runtime
if (!window.chrome) {
  window.chrome = {};
}
if (!window.chrome.runtime) {
  window.chrome.runtime = {
    onConnect: { addListener: function () {} },
    onMessage: { addListener: function () {} },
  };
}
if (!window.chrome.loadTimes) {
  window.chrome.loadTimes = function () { return {}; };
}
if (!window.chrome.csi) {
  window.chrome.csi = function () { return {}; };
}

// 3. Permissions API — headless returns 'denied' for notifications
const originalQuery = window.navigator.permissions?.query?.bind(window.navigator.permissions);
if (originalQuery) {
  window.navigator.permissions.query = function (parameters) {
    if (parameters.name === 'notifications') {
      return Promise.resolve({ state: Notification.permission });
    }
    return originalQuery(parameters);
  };
}

// 4. Plugins — headless has empty plugins array
if (navigator.plugins.length === 0) {
  Object.defineProperty(navigator, 'plugins', {
    get: () => {
      const plugins = [
        { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
        { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
        { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' },
      ];
      plugins.refresh = function () {};
      plugins.item = function (i) { return this[i] || null; };
      plugins.namedItem = function (name) { return this.find(p => p.name === name) || null; };
      return plugins;
    },
    configurable: true,
  });
}

// 5. Languages — ensure realistic value
if (!navigator.languages || navigator.languages.length === 0) {
  Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en'],
    configurable: true,
  });
}

// 6. Connection — headless may lack navigator.connection
if (!navigator.connection) {
  Object.defineProperty(navigator, 'connection', {
    get: () => ({
      effectiveType: '4g',
      rtt: 50,
      downlink: 10,
      saveData: false,
    }),
    configurable: true,
  });
}

// 7. Hardware concurrency — default to a realistic value
if (navigator.hardwareConcurrency === 0 || navigator.hardwareConcurrency === undefined) {
  Object.defineProperty(navigator, 'hardwareConcurrency', {
    get: () => 8,
    configurable: true,
  });
}

// 8. DeviceMemory — headless may report 0
if (!navigator.deviceMemory) {
  Object.defineProperty(navigator, 'deviceMemory', {
    get: () => 8,
    configurable: true,
  });
}

// 9. WebGL vendor/renderer — headless shows "Google Inc." / "ANGLE" which is a red flag
const getParameterProxyHandler = {
  apply: function (target, thisArg, args) {
    const param = args[0];
    const gl = thisArg;
    // UNMASKED_VENDOR_WEBGL
    if (param === 0x9245) {
      return 'Intel Inc.';
    }
    // UNMASKED_RENDERER_WEBGL
    if (param === 0x9246) {
      return 'Intel Iris OpenGL Engine';
    }
    return Reflect.apply(target, thisArg, args);
  },
};

try {
  const canvas = document.createElement('canvas');
  const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
  if (gl) {
    const debugInfo = gl.getExtension('WEBGL_debug_renderer_info');
    if (debugInfo) {
      WebGLRenderingContext.prototype.getParameter = new Proxy(
        WebGLRenderingContext.prototype.getParameter,
        getParameterProxyHandler,
      );
    }
  }
} catch (e) {
  // WebGL not available — skip
}

// 10. Prevent detection via stack trace analysis (Playwright injection markers)
const originalError = Error;
const originalPrepareStackTrace = Error.prepareStackTrace;
if (typeof Error.prepareStackTrace === 'function') {
  Error.prepareStackTrace = function (err, stack) {
    // Filter out Playwright-related frames
    const filteredStack = stack.filter(
      frame => !String(frame.getFileName()).includes('pptr:') &&
               !String(frame.getFileName()).includes('playwright'),
    );
    if (originalPrepareStackTrace) {
      return originalPrepareStackTrace(err, filteredStack);
    }
    return filteredStack.map(f => `    at ${f}`).join('\n');
  };
}

// 11. iframe contentWindow — headless iframes lack proper contentWindow
// (Used by bot detection to check if iframes are real)
try {
  const originalHTMLIFrameElement = HTMLIFrameElement.prototype.__lookupGetter__('contentWindow');
  if (originalHTMLIFrameElement) {
    Object.defineProperty(HTMLIFrameElement.prototype, 'contentWindow', {
      get: function () {
        const result = originalHTMLIFrameElement.call(this);
        if (result === null) {
          // Return a minimal window-like object for detached iframes
          return window;
        }
        return result;
      },
      configurable: true,
    });
  }
} catch (e) {
  // Skip if not supported
}
