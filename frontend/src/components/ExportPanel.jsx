import { useState, useEffect } from "react";
import { createListing, aiDescribe, getEtsyStatus, connectEtsy, disconnectEtsy, publishToEtsy } from "../services/api.js";

export default function ExportPanel({
  result,
  onGenerate,
  onDownload,
  onDownloadDXF,
  onDownloadSTL,
  onDownloadThumbnail,
  onDownloadPrintPNG,
  onDownloadEtsyListing,
  onDownloadEtsyPackage,
  onDownloadPreview,
  canGenerate,
  generating,
  user,
  printDPI,
  etsyShopUrl,
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
  const [downloading, setDownloading] = useState(null);
  const [downloadDone, setDownloadDone] = useState(null);

  // Etsy connection state
  const [etsyStatus, setEtsyStatus] = useState({ connected: false });
  const [etsyPublishing, setEtsyPublishing] = useState(false);
  const [etsyResult, setEtsyResult] = useState(null);

  const isPrint = true;

  useEffect(() => {
    if (user) {
      getEtsyStatus().then(setEtsyStatus).catch(() => {});
    }
  }, [user]);

  // Check for ?etsy_connected=1 in URL (OAuth callback redirect)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("etsy_connected") === "1") {
      getEtsyStatus().then(setEtsyStatus).catch(() => {});
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, []);

  async function handleDownloadWithFeedback(fn, key) {
    setDownloading(key);
    setDownloadDone(null);
    try {
      await fn();
      setDownloadDone(key);
      setTimeout(() => setDownloadDone(null), 1500);
    } finally {
      setDownloading(null);
    }
  }

  function dlLabel(label, key) {
    if (downloading === key) return <span className="generate-btn-content"><span className="spinner-inline" /> Downloading...</span>;
    if (downloadDone === key) return `\u2713 ${label}`;
    return label;
  }

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
      setListError(err.message);
    } finally {
      setAiLoading(false);
    }
  }

  async function handleConnectEtsy() {
    try {
      const { auth_url } = await connectEtsy();
      window.location.href = auth_url;
    } catch (err) {
      setListError(err.message);
    }
  }

  async function handleDisconnectEtsy() {
    try {
      await disconnectEtsy();
      setEtsyStatus({ connected: false });
    } catch (err) {
      setListError(err.message);
    }
  }

  async function handlePublishToEtsy() {
    if (!result) return;
    setEtsyPublishing(true);
    setListError(null);
    setEtsyResult(null);
    try {
      const res = await publishToEtsy(
        result.file_id,
        listTitle || result.location_name,
        listDesc || `Beautiful CNC-ready map of ${result.location_name}. Digital download includes SVG source file.`,
        parseFloat(listPrice) || 9.99,
        listTags,
      );
      setEtsyResult(res);
    } catch (err) {
      setListError(err.message);
    } finally {
      setEtsyPublishing(false);
    }
  }

  const canSell = user && (user.tier === "maker" || user.tier === "pro" || user.tier === "admin");

  const isAdmin = user?.tier === "admin";

  return (
    <div className="export-section">
      <h2>Generate & Download</h2>

      {/* Generate button — available to everyone for previewing */}
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
        <p className="export-hint">Select a location above to generate a preview</p>
      )}

      {/* Non-admin visitors: show "Buy on Etsy" CTA after they generate a preview */}
      {result && !isAdmin && (
        <div className="etsy-cta-section">
          <div className="etsy-cta-card">
            <h3>Love your design?</h3>
            <p>Get your print-ready files — high-resolution PNG, SVG source, and mockup image.</p>
            <a
              href={etsyShopUrl || "https://www.etsy.com"}
              target="_blank"
              rel="noopener noreferrer"
              className="btn btn-etsy btn-full etsy-buy-btn"
            >
              Buy on Etsy — Get Your Files
            </a>
            <p className="etsy-cta-note">
              After purchase, you'll receive a unique link to download your custom print-ready files.
            </p>
          </div>
        </div>
      )}

      {/* File stats — visible to everyone after generating a preview */}
      {result && (
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
      )}

      {/* Download buttons + Etsy tools — admin only */}
      {result && isAdmin && (
        <>
          <div className="export-download-section">
            <div className="export-buttons">
                  {result.print_png_available && (
                    <button className="btn btn-primary" disabled={!!downloading} onClick={() => handleDownloadWithFeedback(onDownloadPrintPNG, "print")}>
                      {dlLabel(`Download Print PNG (${printDPI || 300} DPI)`, "print")}
                    </button>
                  )}
                  {result.etsy_listing_available && (
                    <button className="btn btn-secondary" disabled={!!downloading} onClick={() => handleDownloadWithFeedback(onDownloadEtsyListing, "etsy")}>
                      {dlLabel("Etsy Listing (2700x2025)", "etsy")}
                    </button>
                  )}
                  <button className="btn btn-primary" disabled={!!downloading} onClick={() => handleDownloadWithFeedback(onDownloadEtsyPackage, "etsy-pkg")}>
                    {dlLabel("Etsy Export Package (ZIP)", "etsy-pkg")}
                  </button>
                  {result.thumbnail_available && (
                    <button className="btn btn-secondary" disabled={!!downloading} onClick={() => handleDownloadWithFeedback(onDownloadThumbnail, "mockup")}>
                      {dlLabel("Etsy Mockup PNG", "mockup")}
                    </button>
                  )}
                  <button className="btn btn-secondary" disabled={!!downloading} onClick={() => handleDownloadWithFeedback(onDownloadPreview, "preview")}>
                    {dlLabel("Watermarked Preview", "preview")}
                  </button>
                  <button className="btn btn-secondary" disabled={!!downloading} onClick={() => handleDownloadWithFeedback(onDownload, "svg")}>
                    {dlLabel("SVG Source", "svg")}
                  </button>
                  {result.dxf_available && (
                    <button className="btn btn-secondary" disabled={!!downloading} onClick={() => handleDownloadWithFeedback(onDownloadDXF, "dxf")}>
                      {dlLabel("DXF (VCarve/CAM)", "dxf")}
                    </button>
                  )}
                  {result.stl_available && (
                    <button className="btn btn-secondary btn-3d" disabled={!!downloading} onClick={() => handleDownloadWithFeedback(onDownloadSTL, "stl")}>
                      {dlLabel("3D STL (Bathymetric)", "stl")}
                    </button>
                  )}
            </div>
          </div>

          {/* Etsy Connection Status */}
          {user && (
            <div className="etsy-connection-section">
              {etsyStatus.connected ? (
                <div className="etsy-connected">
                  <span className="etsy-badge">Etsy Connected: {etsyStatus.shop_name || "Your Shop"}</span>
                  <button className="btn btn-sm btn-secondary" onClick={handleDisconnectEtsy}>
                    Disconnect
                  </button>
                </div>
              ) : (
                <button className="btn btn-etsy btn-full" onClick={handleConnectEtsy}>
                  Connect Etsy Shop
                </button>
              )}
            </div>
          )}

          {/* Sell / Publish Section */}
          {canSell && !showListForm && (
            <div className="sell-buttons">
              <button
                className="btn btn-marketplace btn-full"
                onClick={() => {
                  setListTitle(result.location_name);
                  setShowListForm(true);
                  setListSuccess(false);
                  setListError(null);
                  setEtsyResult(null);
                }}
              >
                {etsyStatus.connected ? "Sell on Marketplace / Etsy" : "Sell on Marketplace"}
              </button>
            </div>
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
              {etsyResult && (
                <div className="success-message">
                  Draft listing created on Etsy!{" "}
                  <a href={etsyResult.listing_url} target="_blank" rel="noopener noreferrer">
                    View on Etsy
                  </a>
                </div>
              )}

              <div className="list-form-actions">
                <button
                  className="btn btn-primary btn-full"
                  onClick={handleList}
                  disabled={listing || listSuccess}
                >
                  {listing ? "Listing..." : listSuccess ? "Listed!" : "Publish to Marketplace"}
                </button>

                {etsyStatus.connected && (
                  <button
                    className="btn btn-etsy btn-full"
                    onClick={handlePublishToEtsy}
                    disabled={etsyPublishing || !!etsyResult}
                  >
                    {etsyPublishing ? (
                      <span className="generate-btn-content">
                        <span className="spinner-inline" /> Publishing to Etsy...
                      </span>
                    ) : etsyResult ? (
                      "Published to Etsy!"
                    ) : (
                      "Publish to Etsy (Draft)"
                    )}
                  </button>
                )}
              </div>
            </div>
          )}

        </>
      )}
    </div>
  );
}
