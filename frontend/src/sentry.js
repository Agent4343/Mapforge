/**
 * Frontend Sentry shim.
 *
 * Gated on `VITE_SENTRY_DSN` being set at build time. When unset
 * (dev, tests, any env that skipped the build arg) every export
 * here is a no-op — Sentry never ships in the bundle beyond a few
 * kilobytes of stubbed calls.
 *
 * Using the standalone `@sentry/browser` rather than
 * `@sentry/react` keeps the bundle ~30KB smaller: we don't need
 * React-specific profiler or routing integrations, only
 * `captureException` from our ErrorBoundary and from `fetch`
 * catch branches in `api.js`.
 */

import * as Sentry from "@sentry/browser";

const DSN = import.meta.env.VITE_SENTRY_DSN || "";
const RELEASE = import.meta.env.VITE_GIT_SHA || "";
const ENV = import.meta.env.MODE || "production";

let initialized = false;

export function initSentry() {
  if (initialized || !DSN) return;
  try {
    Sentry.init({
      dsn: DSN,
      release: RELEASE || undefined,
      environment: ENV,
      // We use our own ErrorBoundary for render errors, but
      // `globalHandlersIntegration` catches top-level uncaught
      // exceptions and unhandled promise rejections — those
      // bypass React entirely.
      // 10% transactions sample rate matches the server default
      // in app.config so server + browser traces align.
      tracesSampleRate: 0.1,
      // Strip PII by default. Add allow-listed tags at the call
      // site when you need to correlate a specific user.
      sendDefaultPii: false,
    });
    initialized = true;
  } catch (err) {
    // Never let Sentry init itself be a source of a crash.
    // eslint-disable-next-line no-console
    console.warn("Sentry init failed:", err);
  }
}

export function captureException(err, context) {
  if (!initialized) return;
  try {
    if (context) {
      Sentry.withScope((scope) => {
        for (const [k, v] of Object.entries(context)) {
          scope.setContext(k, v);
        }
        Sentry.captureException(err);
      });
    } else {
      Sentry.captureException(err);
    }
  } catch (_) {
    /* swallow — crash reporting must never crash */
  }
}

// Exposed so callers can check whether Sentry is actually live
// without importing @sentry/browser directly.
export function isSentryEnabled() {
  return initialized;
}
