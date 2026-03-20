import { useState } from "react";

export default function ExportPanel({
  result,
  onGenerate,
  onDownloadPrintPNG,
  onSaveDesign,
  designId,
  canGenerate,
  generating,
}) {
  const [savingDesign, setSavingDesign] = useState(false);
  const [copied, setCopied] = useState(false);

  return (
    <div className="export-section">
      {/* Generate button */}
      <button
        className="btn btn-primary btn-full generate-btn"
        onClick={onGenerate}
        disabled={!canGenerate || generating}
      >
        {generating ? (
          <span className="generate-btn-content">
            <span className="spinner-inline" /> Generating preview...
          </span>
        ) : (
          "Preview My Print"
        )}
      </button>

      {!canGenerate && !result && (
        <p className="export-hint">Search for a location above to start designing</p>
      )}

      {/* After generation — show save design + design ID */}
      {result && (
        <>
          {/* Save Design & Get ID — the core Etsy workflow */}
          {!designId ? (
            <button
              className="btn btn-full"
              onClick={async () => {
                setSavingDesign(true);
                await onSaveDesign();
                setSavingDesign(false);
              }}
              disabled={savingDesign}
              style={{
                background: "linear-gradient(135deg, #27ae60, #2ecc71)",
                color: "#fff",
                border: "none",
                fontWeight: "bold",
                fontSize: "15px",
                padding: "14px",
                marginTop: "8px",
              }}
            >
              {savingDesign ? "Saving..." : "Save Design & Get Design ID"}
            </button>
          ) : (
            <div style={{
              background: "rgba(39, 174, 96, 0.08)",
              border: "2px solid #27ae60",
              borderRadius: "10px",
              padding: "20px",
              textAlign: "center",
              marginTop: "8px",
            }}>
              <div style={{ fontSize: "10px", color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: "1.5px", marginBottom: "6px" }}>
                Your Design ID
              </div>
              <div style={{
                fontSize: "32px",
                fontWeight: "bold",
                fontFamily: "var(--font-mono)",
                color: "#27ae60",
                letterSpacing: "3px",
                marginBottom: "10px",
              }}>
                {designId}
              </div>
              <p style={{ fontSize: "12px", color: "var(--text-secondary)", margin: "0 0 12px", lineHeight: 1.5 }}>
                Save this ID! Enter it when you order on our Etsy shop.
              </p>
              <button
                className="btn btn-secondary"
                onClick={() => {
                  navigator.clipboard.writeText(designId);
                  setCopied(true);
                  setTimeout(() => setCopied(false), 2000);
                }}
                style={{ fontSize: "12px", padding: "8px 20px" }}
              >
                {copied ? "Copied!" : "Copy to Clipboard"}
              </button>
            </div>
          )}

          {/* Download print file — secondary action */}
          {result.print_png_available && (
            <div style={{ marginTop: "10px" }}>
              <button className="btn btn-secondary btn-full" onClick={onDownloadPrintPNG} style={{ fontSize: "12px" }}>
                Download Preview (300 DPI)
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
