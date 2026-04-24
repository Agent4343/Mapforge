import React from "react";

/**
 * Top-level React error boundary.
 *
 * Without a boundary, a render-time exception anywhere in the tree
 * (a MapLibre init failure, a malformed API response breaking a
 * selector, a component receiving an unexpected shape) unmounts the
 * whole app and the user sees a blank white page with no
 * explanation. With this boundary we show a recoverable error panel,
 * log the crash to the backend (via a plain fetch so it ends up
 * alongside server-side Sentry events), and offer a "Reload" action.
 *
 * Must be a class component — React's error API is still class-only.
 */
export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // Best-effort: send a crash report to the backend so we have a
    // server-side record even if the user closes the tab before we
    // can render anything. Wrapped in try/catch because we do NOT
    // want the error-reporting path to itself throw during a crash.
    try {
      const body = JSON.stringify({
        message: String(error?.message || error),
        stack: String(error?.stack || "").slice(0, 4000),
        componentStack: String(info?.componentStack || "").slice(0, 4000),
        url: window.location.href,
        userAgent: navigator.userAgent,
      });
      // `keepalive` lets the browser finish the POST even if the tab
      // is being torn down. Endpoint is optional; 404 is fine.
      fetch("/api/v1/client-errors", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
        keepalive: true,
      }).catch(() => {});
    } catch (_) {
      /* never throw from an error boundary */
    }
    // eslint-disable-next-line no-console
    console.error("ErrorBoundary caught:", error, info);
  }

  handleReload = () => {
    // Full reload rather than just `setState({error: null})` — the
    // app's state machine is probably in a bad place if we got here.
    window.location.reload();
  };

  render() {
    if (this.state.error) {
      return (
        <div
          role="alert"
          style={{
            minHeight: "100vh",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            padding: "24px",
            fontFamily:
              "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
            color: "#1a1a1a",
            background: "#fafafa",
            textAlign: "center",
          }}
        >
          <div style={{ maxWidth: "480px" }}>
            <h1 style={{ fontSize: "24px", marginBottom: "8px" }}>
              Something went wrong
            </h1>
            <p style={{ color: "#555", marginBottom: "16px" }}>
              The app ran into an unexpected error. Reloading usually
              fixes it. If it keeps happening, please contact support
              and include the reference below.
            </p>
            <code
              style={{
                display: "block",
                fontSize: "12px",
                color: "#888",
                background: "#f0f0f0",
                padding: "8px 10px",
                borderRadius: "4px",
                marginBottom: "16px",
                wordBreak: "break-word",
              }}
            >
              {String(this.state.error?.message || this.state.error)}
            </code>
            <button
              type="button"
              onClick={this.handleReload}
              style={{
                padding: "10px 20px",
                fontSize: "14px",
                border: "none",
                borderRadius: "6px",
                background: "#1a1a1a",
                color: "#fff",
                cursor: "pointer",
              }}
            >
              Reload app
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
