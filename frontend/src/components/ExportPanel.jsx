import { useState, useEffect } from "react";
import { createListing, aiDescribe, getEtsyStatus, connectEtsy, disconnectEtsy, publishToEtsy, getShowcaseCities, showcasePublish } from "../services/api.js";

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
  onDownloadWallMockup,
  canGenerate,
  generating,
  user,
  printDPI,
  etsyShopUrl,
  onStartEtsyCheckout,
  checkoutBlockedReason,
  onOverrideCheckoutBlock,
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

  // Showcase state
  const [showcaseCities, setShowcaseCities] = useState([]);
  const [showShowcase, setShowShowcase] = useState(false);
  const [showcasePublishing, setShowcasePublishing] = useState(null); // city name being published
  const [showcaseResults, setShowcaseResults] = useState({}); // {cityName: {listing_url, ...}}
  const [showcaseError, setShowcaseError] = useState(null);
  const [showcaseTheme, setShowcaseTheme] = useState("classic");
  const [showcaseLayout, setShowcaseLayout] = useState("classic");
  const [showcasePrice, setShowcasePrice] = useState("9.99");

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

  // Load showcase cities when admin opens the showcase panel
  useEffect(() => {
    if (showShowcase && showcaseCities.length === 0 && isAdmin) {
      getShowcaseCities().then(setShowcaseCities).catch(() => {});
    }
  }, [showShowcase]);

  async function handleShowcasePublish(city) {
    setShowcasePublishing(city.name);
    setShowcaseError(null);
    try {
      const res = await showcasePublish(city, {
        color_theme: showcaseTheme,
        poster_layout: showcaseLayout,
        price: parseFloat(showcasePrice) || 9.99,
      });
      setShowcaseResults((prev) => ({ ...prev, [city.name]: res }));
    } catch (err) {
      setShowcaseError(`${city.name}: ${err.message}`);
    } finally {
      setShowcasePublishing(null);
    }
  }

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
      setListError(null);
      const { auth_url } = await connectEtsy();
      if (!auth_url) {
        throw new Error("Etsy connect did not return an authorization URL.");
      }
      window.location.href = auth_url;
    } catch (err) {
      const message = err?.message || "Failed to start Etsy connection.";
      if (/network error|failed to fetch|load failed|timeout/i.test(message)) {
        const baseHint = `${window.location.origin}/api/v1/etsy/connect`;
        setListError(
          `${message} Troubleshooting: 1) Hard refresh this page (Ctrl+Shift+R). ` +
          `2) Sign out and sign back in. 3) Verify backend endpoint is reachable: ${baseHint}`
        );
      } else {
        setListError(message);
      }
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
        listDesc || `Beautiful map poster of ${result.location_name}. High-quality digital download includes print-ready PNG and SVG vector source file.`,
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

      {/* Etsy Connection Status — visible to admin anytime */}
      {isAdmin && user && !result && (
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
          {etsyStatus.connected && !showShowcase && (
            <div>
              <p className="export-hint">Generate a map above, then publish it to Etsy.</p>
              <button
                className="btn btn-marketplace btn-full"
                style={{ marginTop: "8px" }}
                onClick={() => setShowShowcase(true)}
              >
                Push Showcase Maps to Etsy
              </button>
            </div>
          )}
        </div>
      )}

      {/* Showcase Maps Panel — admin only, push preset cities to Etsy */}
      {isAdmin && showShowcase && etsyStatus.connected && (
        <div className="showcase-panel">
          <div className="list-form-header">
            <h3>Showcase Maps</h3>
            <button className="list-form-close" onClick={() => setShowShowcase(false)}>&times;</button>
          </div>
          <p className="export-hint">One-click generate + publish maps to your Etsy shop as draft listings.</p>

          <div className="showcase-options">
            <div className="control-group">
              <label>Theme</label>
              <select value={showcaseTheme} onChange={(e) => setShowcaseTheme(e.target.value)}>
                <option value="classic">Classic</option>
                <option value="modern_dark">Modern Dark</option>
                <option value="midnight">Midnight</option>
                <option value="rose_gold">Rose Gold</option>
                <option value="sage">Sage</option>
                <option value="minimal">Minimal</option>
                <option value="ocean_depths">Ocean Depths</option>
                <option value="sunset_warm">Sunset Warm</option>
                <option value="nordic_frost">Nordic Frost</option>
                <option value="desert_sand">Desert Sand</option>
                <option value="forest_green">Forest Green</option>
                <option value="lavender_mist">Lavender Mist</option>
                <option value="charcoal_gold">Charcoal Gold</option>
                <option value="coastal_blue">Coastal Blue</option>
                <option value="vintage_sepia">Vintage Sepia</option>
              </select>
            </div>
            <div className="control-group">
              <label>Layout</label>
              <select value={showcaseLayout} onChange={(e) => setShowcaseLayout(e.target.value)}>
                <option value="classic">Classic</option>
                <option value="minimal">Minimal</option>
                <option value="editorial">Editorial</option>
                <option value="bold">Bold</option>
                <option value="vintage">Vintage</option>
              </select>
            </div>
            <div className="control-group">
              <label>Price (USD)</label>
              <input
                type="number"
                min="1.99"
                max="99.99"
                step="0.01"
                value={showcasePrice}
                onChange={(e) => setShowcasePrice(e.target.value)}
              />
            </div>
          </div>

          {showcaseError && <div className="error-message">{showcaseError}</div>}

          <div className="showcase-cities-grid">
            {showcaseCities.map((city) => {
              const published = showcaseResults[city.name];
              const isPublishing = showcasePublishing === city.name;
              return (
                <div key={city.osm_id} className="showcase-city-card">
                  <span className="showcase-city-name">{city.name}</span>
                  <span className="showcase-city-region">{city.province}, {city.country.toUpperCase()}</span>
                  {published ? (
                    <a
                      href={published.listing_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="btn btn-sm btn-secondary showcase-done-btn"
                    >
                      View on Etsy
                    </a>
                  ) : (
                    <button
                      className="btn btn-sm btn-etsy"
                      disabled={!!showcasePublishing}
                      onClick={() => handleShowcasePublish(city)}
                    >
                      {isPublishing ? (
                        <span className="generate-btn-content">
                          <span className="spinner-inline" /> Publishing...
                        </span>
                      ) : (
                        "Publish"
                      )}
                    </button>
                  )}
                </div>
              );
            })}
          </div>

          {showcaseCities.length === 0 && (
            <p className="export-hint">Loading showcase cities...</p>
          )}

          {Object.keys(showcaseResults).length > 0 && (
            <p className="success-message">
              {Object.keys(showcaseResults).length} listing(s) published as drafts on Etsy!
            </p>
          )}

          <div className="showcase-info">
            <p className="export-hint" style={{ marginTop: "12px", fontSize: "11px", lineHeight: "1.5" }}>
              <strong>Pre-made maps</strong> — buyers get the actual PNG + SVG files instantly after purchase.
              <br />
              <strong>Custom maps</strong> — use the regular "Sell on Marketplace / Etsy" button after generating any map. Buyers get a design credit to create their own.
            </p>
          </div>
        </div>
      )}

      {/* Non-admin visitors: show Etsy handoff CTA after they generate a preview */}
      {result && !isAdmin && etsyShopUrl && (
        <div className="etsy-cta-section">
          <div className="etsy-cta-card">
            <h3>Love your design?</h3>
            <p>Get your print-ready files — high-resolution PNG, SVG source, and mockup image.</p>
            {checkoutBlockedReason && (
              <div
                className="error-message"
                style={{ marginBottom: "10px", fontSize: "12px" }}
              >
                {checkoutBlockedReason}
              </div>
            )}
            {typeof onStartEtsyCheckout === "function" ? (
              <button
                type="button"
                className="btn btn-etsy btn-full etsy-buy-btn"
                onClick={onStartEtsyCheckout}
                disabled={!!checkoutBlockedReason}
              >
                Continue to Etsy Checkout
              </button>
            ) : (
              <a
                href={etsyShopUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="btn btn-etsy btn-full etsy-buy-btn"
              >
                Buy on Etsy — Get Your Files
              </a>
            )}
            {checkoutBlockedReason && typeof onOverrideCheckoutBlock === "function" && (
              <button
                type="button"
                className="btn btn-secondary btn-full"
                style={{ marginTop: "8px" }}
                onClick={onOverrideCheckoutBlock}
              >
                Continue Anyway
              </button>
            )}
            <p className="etsy-cta-note">
              {typeof onStartEtsyCheckout === "function"
                ? "We'll save this design and include a reference so you can continue after Etsy checkout."
                : "After purchase, you'll receive a unique link to download your custom print-ready files."}
            </p>
          </div>
        </div>
      )}

      {/* File stats — visible to everyone after generating a preview */}
      {result && (
        <div className="file-stats-grid">
            <div className="file-stat">
              <span className="file-stat-label">Size</span>
              <span className="file-stat-value">{Math.round(result.dimensions_mm[0] * 10) / 10}&times;{Math.round(result.dimensions_mm[1] * 10) / 10}mm</span>
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
                  <button className="btn btn-secondary" disabled={!!downloading} onClick={() => handleDownloadWithFeedback(() => onDownloadWallMockup("light_wall"), "mockup-light")}>
                    {dlLabel("Wall Mockup (Light)", "mockup-light")}
                  </button>
                  <button className="btn btn-secondary" disabled={!!downloading} onClick={() => handleDownloadWithFeedback(() => onDownloadWallMockup("dark_wall"), "mockup-dark")}>
                    {dlLabel("Wall Mockup (Dark)", "mockup-dark")}
                  </button>
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


        </>
      )}

      {/* Sell / Publish Section — available to maker/pro/admin */}
      {result && canSell && !showListForm && (
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

      {result && showListForm && (
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
    </div>
  );
}
