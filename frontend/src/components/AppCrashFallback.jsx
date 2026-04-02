export default function AppCrashFallback({ error }) {
  const message = error?.message ? String(error.message) : "Unknown startup error";
  return (
    <div
      style={{
        minHeight: "100vh",
        background: "#0d0d0d",
        color: "#e8e8e8",
        fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
        padding: "24px",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <div
        style={{
          maxWidth: "560px",
          width: "100%",
          background: "#1a1a1a",
          border: "1px solid #333",
          borderRadius: "10px",
          padding: "20px",
        }}
      >
        <h2 style={{ marginTop: 0, marginBottom: "10px" }}>MapForge failed to open</h2>
        <p style={{ marginTop: 0, color: "#b8b8b8", lineHeight: 1.5 }}>
          Your browser blocked a startup dependency (usually storage/privacy mode or strict content filters).
        </p>
        <ol style={{ color: "#cfcfcf", lineHeight: 1.6, paddingLeft: "18px" }}>
          <li>Refresh this page</li>
          <li>Try Private/Incognito mode</li>
          <li>Disable content blockers for this site</li>
        </ol>
        <details style={{ marginTop: "10px", color: "#aaa" }}>
          <summary>Technical details</summary>
          <pre
            style={{
              marginTop: "10px",
              background: "#101010",
              border: "1px solid #2a2a2a",
              borderRadius: "6px",
              padding: "10px",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
            }}
          >
            {message}
          </pre>
        </details>
      </div>
    </div>
  );
}
