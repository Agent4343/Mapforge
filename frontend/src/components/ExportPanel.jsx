import { useState } from "react";
import { createListing, aiDescribe } from "../services/api.js";

export default function ExportPanel({
  result,
  onGenerate,
  onDownload,
  onDownloadThumbnail,
  onDownloadPrintPNG,
  onDownloadEtsyListing,
  onDownloadPreview,
  canGenerate,
  generating,
  user,
  printDPI,
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

  const isPrint = true; // Always print/poster mode

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
      <h2>Generate & Download</h2>

      <button
        className="btn btn-primary btn-full generate-btn"
        onClick={onGenerate}
        disabled={!canGenerate || generating}
      >
        {generating ? (
          <span className="generate-btn-content">
            <span className="spinner-inline" /> Generating...
          </span>
        ) : (
          "Generate Map"
        )}
      </button>

      {!canGenerate && !result && (
        <p className="export-hint">Select a location above to generate</p>
      )}

      {result && (
        <>
          {/* File Stats */}
          <div className="file-stats-grid">
            <div className="file-stat">
              <span className="file-stat-label">Size</span>
              <span className="file-stat-value">{result.dimensions_mm[0]}&times;{result.dimensions_mm[1]}mm</span>
            </div>
            <div className="file-stat">
              <span className="file-stat-label">Nodes</span>
              <span className="file-stat-value">{result.node_count.toLocaleString()}</span>
            </div>
            <div className="file-stat">
              <span className="file-stat-label">Paths</span>
              <span className="file-stat-value">{result.path_count}</span>
            </div>
            <div className="file-stat">
              <span className="file-stat-label">Layers</span>
              <span className="file-stat-value">{result.layer_count}</span>
            </div>
            {isPrint && result.print_pixels && (
              <div className="file-stat">
                <span className="file-stat-label">Pixels</span>
                <span className="file-stat-value">{result.print_pixels[0]}&times;{result.print_pixels[1]}</span>
              </div>
            )}
            {isPrint && result.print_dpi && (
              <div className="file-stat">
                <span className="file-stat-label">DPI</span>
                <span className="file-stat-value">{result.print_dpi}</span>
              </div>
            )}
          </div>

          {/* Download Buttons */}
          <div className="export-download-section">
            <div className="export-buttons">
                  {result.print_png_available && (
                    <button className="btn btn-primary" onClick={onDownloadPrintPNG}>
                      Download Print PNG ({printDPI || 300} DPI)
                    </button>
                  )}
                  {result.etsy_listing_available && (
                    <button className="btn btn-secondary" onClick={onDownloadEtsyListing}>
                      Etsy Listing (2700x2025)
                    </button>
                  )}
                  {result.thumbnail_available && (
                    <button className="btn btn-secondary" onClick={onDownloadThumbnail}>
                      Etsy Mockup PNG
                    </button>
                  )}
                  <button className="btn btn-secondary" onClick={onDownloadPreview}>
                    Watermarked Preview
                  </button>
                  <button className="btn btn-secondary" onClick={onDownload}>
                    SVG Source
                  </button>
            </div>
          </div>

          {/* AI + Marketplace Section */}
          {canSell && !showListForm && (
            <button
              className="btn btn-marketplace btn-full"
              onClick={() => {
                setListTitle(result.location_name);
                setShowListForm(true);
                setListSuccess(false);
                setListError(null);
              }}
            >
              Sell on Marketplace
            </button>
          )}

          {showListForm && (
            <div className="list-form">
              <div className="list-form-header">
                <h3>Create Listing</h3>
                <button className="list-form-close" onClick={() => setShowListForm(false)}>
                  &times;
                </button>
              </div>

              {/* AI Assist Button */}
              <button
                className="btn btn-ai btn-full"
                onClick={handleAiDescribe}
                disabled={aiLoading}
              >
                {aiLoading ? (
                  <span className="generate-btn-content">
                    <span className="spinner-inline" /> AI Writing...
                  </span>
                ) : (
                  "AI Write Title, Description & Tags"
                )}
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
                  placeholder="Describe the design, style, and what makes it unique..."
                  maxLength={2000}
                  rows={5}
                  className="list-textarea"
                />
              </div>
              <div className="control-group">
                <label>Tags</label>
                <input
                  type="text"
                  value={listTags}
                  onChange={(e) => setListTags(e.target.value)}
                  placeholder="lake, cottage, muskoka, wall art, map print"
                  maxLength={500}
                />
              </div>
              {listError && <div className="error-message">{listError}</div>}
              {listSuccess && <div className="success-message">Listed on Marketplace!</div>}
              <button
                className="btn btn-primary btn-full"
                onClick={handleList}
                disabled={listing || listSuccess}
              >
                {listing ? "Listing..." : listSuccess ? "Listed!" : "Publish Listing"}
              </button>
            </div>
          )}

          {!canSell && user && user.tier === "free" && (
            <p className="export-hint">
              Upgrade to Maker to sell on the marketplace.
            </p>
          )}
        </>
      )}
    </div>
  );
}
