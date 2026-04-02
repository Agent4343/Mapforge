import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import AppErrorBoundary from "./components/AppErrorBoundary.jsx";
import "./styles/global.css";
import AppCrashFallback from "./components/AppCrashFallback.jsx";

function boot() {
  const rootEl = document.getElementById("root");
  if (!rootEl) {
    throw new Error("Missing #root mount element");
  }
  ReactDOM.createRoot(rootEl).render(
    <React.StrictMode>
      <AppErrorBoundary>
        <App />
      </AppErrorBoundary>
    </React.StrictMode>
  );
}

try {
  boot();
} catch (error) {
  // Last-resort fallback if React boot itself throws before boundary mounts.
  const rootEl = document.getElementById("root");
  if (rootEl) {
    ReactDOM.createRoot(rootEl).render(<AppCrashFallback error={error} />);
  }
}
