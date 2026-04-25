import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import ErrorBoundary from "./components/ErrorBoundary.jsx";
import { initSentry } from "./sentry.js";
import "./styles/global.css";

// Initialise Sentry FIRST so errors thrown during `App` import /
// first render reach it. No-op if VITE_SENTRY_DSN isn't set.
initSentry();

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>
);
