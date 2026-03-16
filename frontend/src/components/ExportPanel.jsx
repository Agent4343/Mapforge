import { useState } from "react";
import { createListing, aiDescribe } from "../services/api.js";

export default function ExportPanel({
  result,
  onGenerate,
  onDownload,
  onDownloadDXF,
  onDownloadThumbnail,
  onDownloadPrintPNG,
  canGenerate,
  generating,
  user,
}) {
  const [showListForm, setShowListForm] = useState(false);
  const [listTitle, setListTitle] = useState("");
  const [listPrice, setListPrice] = useState("9.99");
  const [listDesc, setListDesc] = useState("");
  const [listTags, setListTags] = useState("");
  const [listError, setListError] = useState(null);
  const [listSuccess, setListSuccess] = useState(false);
  const [listing, setListing] = useState(false);
  const [aiLoading, setAiLoading] = useState(false);

  async function handleList() {
    if (!result) return;
    setListing(true);
    setListError(null);
    setListSuccess(false);
    try {
      await createListing(
        result.file_id,
        listTitle || result.location_name,
        Math.round(parseFloat(listPrice) * 100),
        listDesc,
        listTags,
      );
      setListSuccess(true);
      setTimeout(() => {
        setShowListForm(false);
        setListTitle("");
        setListDesc("");
        setListTags("");
        setListSuccess(false);
      }, 2000);
    } catch (err) {
      setListError(err.message);
    } finally {
      setListing(false);
    }
  }

  async function handleAiDescribe() {
    if (!result) return;
    setAiLoading(true);
    setListError(null);
    try {
      const ai = await aiDescribe(
        result.location_name,
        result.style || "filled",
        result.country || "",
        result.product_type === "city",
        result.province || "",
      );
      if (ai.title) setListTitle(ai.title);
      if (ai.description) setListDesc(ai.description);
      if (ai.tags) setListTags(ai.tags);
    } catch (err) {
      setListError("AI: " + err.message);
    } finally {
      setAiLoading(false);
    }
  }

  const canSell = user && (user.tier === "maker" || user.tier === "pro" || user.tier === "admin");

  return (
    <div className="export-section">
      <h2>Export</h2>

      <button
        className="btn btn-primary btn-full"
        onClick={onGenerate}
        disabled={!canGenerate || generating}
      >
        {generating ? "Generating..." : "Generate SVG"}
      </button>

      {result && (
        <>
          <div className="file-stats">
            <span>
              Dims: <span className="stat-value">{result.dimensions_mm[0]}x{result.dimensions_mm[1]}mm</span>
            </span>
            <span>
              Nodes: <span className="stat-value">{result.node_count}</span>
            </span>
            <span>
              Paths: <span className="stat-value">{result.path_count}</span>
            </span>
          </div>

          <div className="export-buttons">
            <button className="btn btn-secondary" onClick={onDownload}>
              Download SVG
            </button>
            {result.dxf_available && (
              <button className="btn btn-secondary" onClick={onDownloadDXF}>
                Download DXF
              </button>
            )}
            {result.thumbnail_available && (
              <button className="btn btn-secondary" onClick={onDownloadThumbnail}>
                PNG Mockup
              </button>
            )}
            {result.print_png_available && (
              <button className="btn btn-secondary" onClick={onDownloadPrintPNG}>
                Print PNG (300 DPI)
              </button>
            )}
          </div>

          {canSell && !showListForm && (
            <button
              className="btn btn-secondary btn-full"
              onClick={() => {
                setListTitle(result.location_name);
                setShowListForm(true);
                setListSuccess(false);
                setListError(null);
              }}
              style={{ marginTop: 8 }}
            >
              List on Marketplace
            </button>
          )}

          {showListForm && (
            <div className="list-form">
              <button
                className="btn btn-secondary btn-full"
                onClick={handleAiDescribe}
                disabled={aiLoading}
                style={{ marginBottom: 8, background: "var(--accent-hover, #5a3d2b)", color: "#fff" }}
              >
                {aiLoading ? "AI Writing..." : "AI Write Listing"}
              </button>
              <div className="control-group">
                <label>Title</label>
                <input type="text" value={listTitle} onChange={(e) => setListTitle(e.target.value)} maxLength={255} />
              </div>
              <div className="control-group">
                <label>Price (USD)</label>
                <input
                  type="number"
                  min="1.99"
                  max="99.99"
                  step="0.01"
                  value={listPrice}
                  onChange={(e) => setListPrice(e.target.value)}
                />
              </div>
              <div className="control-group">
                <label>Description</label>
                <textarea
                  value={listDesc}
                  onChange={(e) => setListDesc(e.target.value)}
                  placeholder="Describe the design, wood recommendations..."
                  maxLength={2000}
                  rows={6}
                  style={{ width: "100%", resize: "vertical", fontFamily: "inherit", fontSize: "12px" }}
                />
              </div>
              <div className="control-group">
                <label>Tags (comma-separated)</label>
                <input type="text" value={listTags} onChange={(e) => setListTags(e.target.value)} placeholder="lake, cottage, muskoka" maxLength={500} />
              </div>
              {listError && <div className="error-message">{listError}</div>}
              {listSuccess && <div className="success-message">Listed successfully! View it in the Marketplace.</div>}
              <div className="export-buttons">
                <button className="btn btn-primary" onClick={handleList} disabled={listing || listSuccess}>
                  {listing ? "Listing..." : listSuccess ? "Listed!" : "List for Sale"}
                </button>
                <button className="btn btn-secondary" onClick={() => setShowListForm(false)}>
                  Cancel
                </button>
              </div>
            </div>
          )}

          {!canSell && user && user.tier === "free" && (
            <p style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "8px", textAlign: "center" }}>
              Upgrade to Maker to sell your designs on the marketplace.
            </p>
          )}
        </>
      )}
    </div>
  );
}
