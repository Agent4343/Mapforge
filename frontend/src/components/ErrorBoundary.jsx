import { Component } from "react";

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error("ErrorBoundary caught:", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          minHeight: "100vh",
          padding: "40px",
          background: "var(--bg-primary, #0d0d0d)",
          color: "var(--text-primary, #e8e6e3)",
          textAlign: "center",
        }}>
          <h1 style={{ fontSize: "24px", marginBottom: "16px" }}>Something went wrong</h1>
          <p style={{ color: "var(--text-muted, #888)", marginBottom: "24px", maxWidth: "500px" }}>
            An unexpected error occurred. Please try refreshing the page.
          </p>
          <button
            onClick={() => window.location.reload()}
            style={{
              padding: "10px 24px",
              background: "var(--crimson, #c0392b)",
              color: "#fff",
              border: "none",
              borderRadius: "6px",
              cursor: "pointer",
              fontSize: "14px",
            }}
          >
            Refresh Page
          </button>
          {this.state.error && (
            <pre style={{
              marginTop: "24px",
              padding: "12px",
              background: "rgba(255,255,255,0.05)",
              borderRadius: "6px",
              fontSize: "11px",
              color: "var(--text-muted, #888)",
              maxWidth: "600px",
              overflow: "auto",
            }}>
              {this.state.error.message}
            </pre>
          )}
        </div>
      );
    }

    return this.props.children;
  }
}
