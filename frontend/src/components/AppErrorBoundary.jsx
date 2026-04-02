import React from "react";
import AppCrashFallback from "./AppCrashFallback.jsx";

export default class AppErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, errorMessage: "" };
  }

  static getDerivedStateFromError(error) {
    return {
      hasError: true,
      errorMessage: error?.message || "App failed to start",
    };
  }

  componentDidCatch(error) {
    // Keep a breadcrumb for troubleshooting in mobile Safari.
    try {
      const msg = error?.message || String(error || "unknown");
      localStorage.setItem("mapforge_last_boot_error", msg);
    } catch {
      // no-op
    }
  }

  render() {
    if (this.state.hasError) {
      return <AppCrashFallback errorMessage={this.state.errorMessage} />;
    }
    return this.props.children;
  }
}
