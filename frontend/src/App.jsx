import { useState, useCallback, useEffect, useRef } from "react";
import SearchPanel from "./components/SearchPanel.jsx";
import CustomizePanel from "./components/CustomizePanel.jsx";
import SVGPreview from "./components/SVGPreview.jsx";
import ExportPanel from "./components/ExportPanel.jsx";
import AuthModal from "./components/AuthModal.jsx";
import LibraryView from "./components/LibraryView.jsx";
import MarketplaceView from "./components/MarketplaceView.jsx";
import SellerDashboard from "./components/SellerDashboard.jsx";
import AdminDashboard from "./components/AdminDashboard.jsx";
import BatchPanel from "./components/BatchPanel.jsx";
import MapPreview from "./components/MapPreview.jsx";
import MarkersPanel from "./components/MarkersPanel.jsx";
import LandingPage from "./components/LandingPage.jsx";
import PricingModal from "./components/PricingModal.jsx";
import PurchasesView from "./components/PurchasesView.jsx";
import {
  generateSVG, generatePin, downloadSVG, downloadDXF, downloadThumbnail, downloadPrintPNG,
  getProfile, logout, getToken, subscribe,
} from "./services/api.js";

const DEFAULT_CONFIG = {
  text: "",
  subtitle: "",
  boardSize: "print_16x20",
  customWidth: 16,
  customHeight: 20,
  style: "filled",
  exportFormat: "svg",
  productType: "city",
  fontSize: 14,
  fontFamily: "sans",
  borderStyle: "none",
  showCoordinates: true,
  includeIslands: true,
  includeStreets: true,
  includeContours: false,
  contourType: "depth",
  numDepthBands: 5,
  outputMode: "print",
  colorTheme: "classic",
  heartLat: null,
  heartLon: null,
};

function loadSavedConfig() {
  try {
    const saved = localStorage.getItem("mapforge_config");
    if (saved) return { ...DEFAULT_CONFIG, ...JSON.parse(saved) };
  } catch {}
  return DEFAULT_CONFIG;
}

function saveConfig(config) {
  try {
    localStorage.setItem("mapforge_config", JSON.stringify(config));
  } catch {}
}

const MAX_UNDO = 30;

const COUNTRIES = [
  { code: "ca", label: "Canada" },
  { code: "us", label: "United States" },
  { code: "", label: "Global" },
];

export default function App() {
  const [user, setUser] = useState(null);
  const [showAuth, setShowAuth] = useState(false);
  const [showBatch, setShowBatch] = useState(false);
  const [showPricing, setShowPricing] = useState(false);
  const [showLanding, setShowLanding] = useState(!getToken());
  const [view, setView] = useState("main"); // main, library, marketplace, dashboard

  const [selectedResult, setSelectedResult] = useState(null);
  const [config, setConfig] = useState(loadSavedConfig);
  const [svgContent, setSvgContent] = useState(null);
  const [result, setResult] = useState(null);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState(null);
  const [qualityWarning, setQualityWarning] = useState(null);
  const [country, setCountry] = useState("ca");
  const [panelCollapsed, setPanelCollapsed] = useState(false);
  const [pinCoords, setPinCoords] = useState(null); // {lat, lon} for name_sign pin drop
  const [markers, setMarkers] = useState([]); // custom markers [{lat, lon, label, icon}]

  // Undo/redo state
  const [configHistory, setConfigHistory] = useState([config]);
  const [historyIndex, setHistoryIndex] = useState(0);
  const skipHistory = useRef(false);

  // Load user profile if token exists
  useEffect(() => {
    if (getToken()) {
      getProfile().then((p) => { if (p) setUser(p); }).catch(() => {});
    }
  }, []);

  // Auto-save config to localStorage
  useEffect(() => {
    saveConfig(config);
  }, [config]);

  // Config change with undo history
  function handleConfigChange(newConfig) {
    if (skipHistory.current) {
      skipHistory.current = false;
      setConfig(newConfig);
      return;
    }
    const newHistory = configHistory.slice(0, historyIndex + 1);
    newHistory.push(newConfig);
    if (newHistory.length > MAX_UNDO) newHistory.shift();
    setConfigHistory(newHistory);
    setHistoryIndex(newHistory.length - 1);
    setConfig(newConfig);
  }

  function handleUndo() {
    if (historyIndex <= 0) return;
    const newIndex = historyIndex - 1;
    setHistoryIndex(newIndex);
    skipHistory.current = true;
    setConfig(configHistory[newIndex]);
  }

  function handleRedo() {
    if (historyIndex >= configHistory.length - 1) return;
    const newIndex = historyIndex + 1;
    setHistoryIndex(newIndex);
    skipHistory.current = true;
    setConfig(configHistory[newIndex]);
  }

  // Keyboard shortcuts for undo/redo
  useEffect(() => {
    function handleKeyDown(e) {
      if ((e.ctrlKey || e.metaKey) && e.key === "z") {
        e.preventDefault();
        if (e.shiftKey) {
          handleRedo();
        } else {
          handleUndo();
        }
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [historyIndex, configHistory]);

  function handleAuth(userData) {
    setUser(userData);
    setShowAuth(false);
    setShowLanding(false);
  }

  async function handleSubscribe(plan) {
    try {
      const data = await subscribe(plan);
      if (data.checkout_url) {
        window.location.href = data.checkout_url;
      }
    } catch (err) {
      alert(err.message);
    }
  }

  function handleLogout() {
    logout();
    setUser(null);
  }

  function handleSelect(item) {
    setSelectedResult(item);
    const name = item.display_name.split(",")[0].trim();
    handleConfigChange({
      ...config,
      text: name,
      productType: item.feature_type || config.productType,
    });
    setSvgContent(null);
    setResult(null);
    setError(null);

    // Check geometry quality
    if (!item.has_geometry) {
      setQualityWarning("This location may not have polygon data. Generation might fail or produce incomplete results.");
    } else {
      setQualityWarning(null);
    }
  }

  const handleGenerate = useCallback(async () => {
    // Pin-drop mode: use coordinates instead of OSM search result
    const isPinMode = config.productType === "name_sign" && pinCoords;
    if (!selectedResult && !isPinMode) return;

    setGenerating(true);
    setError(null);
    setSvgContent(null);
    setResult(null);

    try {
      let data;

      if (isPinMode) {
        const pinParams = {
          lat: pinCoords.lat,
          lon: pinCoords.lon,
          label: config.text || "My Place",
          subtitle: config.subtitle || "",
          board_size: config.boardSize,
          style: config.outputMode === "print" ? "filled" : config.style,
          export_format: config.outputMode === "print" ? "svg" : config.exportFormat,
          show_coordinates: config.showCoordinates,
          font_size_mm: config.fontSize,
          font_family: config.fontFamily || "sans",
          border_style: config.borderStyle || "none",
          include_streets: config.includeStreets,
          color_theme: config.colorTheme || "classic",
        };
        if (config.boardSize === "custom") {
          pinParams.board_width_inches = config.customWidth || 16;
          pinParams.board_height_inches = config.customHeight || 20;
        }
        data = await generatePin(pinParams);
      } else {
        // Build markers list from valid entries
        const validMarkers = markers
          .filter((m) => m.lat !== "" && m.lon !== "" && !isNaN(m.lat) && !isNaN(m.lon))
          .map((m) => ({
            lat: parseFloat(m.lat),
            lon: parseFloat(m.lon),
            label: m.label || "",
            icon: m.icon || "pin",
          }));

        const params = {
          osm_id: selectedResult.osm_id,
          osm_type: selectedResult.osm_type,
          product_type: config.productType,
          board_size: config.boardSize,
          style: config.outputMode === "print" ? "filled" : config.style,
          export_format: config.outputMode === "print" ? "svg" : config.exportFormat,
          output_mode: config.outputMode || "cnc",
          text: config.text,
          subtitle: config.subtitle || "",
          show_coordinates: config.showCoordinates,
          font_size_mm: config.fontSize,
          font_family: config.fontFamily || "sans",
          border_style: config.borderStyle || "none",
          simplification: "auto",
          include_islands: config.includeIslands,
          min_island_area_m2: 5000,
          include_streets: config.includeStreets,
          include_contours: config.includeContours,
          contour_type: config.contourType,
          num_depth_bands: config.numDepthBands,
          markers: validMarkers,
          color_theme: config.colorTheme || "classic",
          heart_lat: config.heartLat || undefined,
          heart_lon: config.heartLon || undefined,
        };
        if (config.boardSize === "custom") {
          params.board_width_inches = config.customWidth || 16;
          params.board_height_inches = config.customHeight || 20;
        }
        data = await generateSVG(params);
      }

      setSvgContent(data.svg);
      setResult(data);

      // Geometry quality check post-generation
      if (data.node_count < 20) {
        setQualityWarning("Low detail: This location has very few data points. The SVG may appear rough or oversimplified.");
      } else if (data.node_count > 50000) {
        setQualityWarning("High complexity: This file has many nodes and may be slow to process on some CNC controllers. Consider reducing detail.");
      } else {
        setQualityWarning(null);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setGenerating(false);
    }
  }, [selectedResult, config, pinCoords, markers]);

  const handleDownload = useCallback(async () => {
    if (!result) return;
    // If SVG is in memory, download directly without server round-trip
    if (svgContent) {
      const blob = new Blob([svgContent], { type: "image/svg+xml" });
      _triggerDownload(blob, config.text, "svg");
      return;
    }
    try {
      const blob = await downloadSVG(result.file_id);
      _triggerDownload(blob, config.text, "svg");
    } catch (err) {
      setError(err.message);
    }
  }, [result, config.text, svgContent]);

  const handleDownloadDXF = useCallback(async () => {
    if (!result) return;
    try {
      const blob = await downloadDXF(result.file_id);
      _triggerDownload(blob, config.text, "dxf");
    } catch (err) {
      setError(err.message);
    }
  }, [result, config.text]);

  const handleDownloadThumbnail = useCallback(async () => {
    if (!result) return;
    try {
      const blob = await downloadThumbnail(result.file_id);
      _triggerDownload(blob, config.text + "_mockup", "png");
    } catch (err) {
      setError(err.message);
    }
  }, [result, config.text]);

  const handleDownloadPrintPNG = useCallback(async () => {
    if (!result) return;
    try {
      const blob = await downloadPrintPNG(result.file_id);
      _triggerDownload(blob, config.text + "_print_300dpi", "png");
    } catch (err) {
      setError(err.message);
    }
  }, [result, config.text]);

  function _triggerDownload(blob, name, ext) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${(name || "mapforge").replace(/\s+/g, "_").toLowerCase()}.${ext}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  // Landing page for new visitors
  if (showLanding && !user) {
    return (
      <>
        <LandingPage
          onGetStarted={() => setShowLanding(false)}
          onSignIn={() => { setShowAuth(true); }}
        />
        {showAuth && <AuthModal onAuth={handleAuth} onClose={() => setShowAuth(false)} />}
      </>
    );
  }

  // Sub-views
  if (view === "library") return <LibraryView onBack={() => setView("main")} />;
  if (view === "marketplace") return <MarketplaceView user={user} onBack={() => setView("main")} />;
  if (view === "dashboard") return <SellerDashboard onBack={() => setView("main")} />;
  if (view === "purchases") return <PurchasesView onBack={() => setView("main")} />;
  if (view === "admin") return <AdminDashboard onBack={() => setView("main")} />;

  const canUndo = historyIndex > 0;
  const canRedo = historyIndex < configHistory.length - 1;

  return (
    <div className="app">
      <header className="header">
        <div className="header-brand">
          <div>
            <h1>Map<span>Forge</span></h1>
            <div className="subtitle">
              {config.outputMode === "print"
                ? "Custom Street Map Prints for Etsy & Wall Art"
                : "Geographic SVG Generator for CNC Routing"}
            </div>
          </div>
        </div>
        <nav className="header-nav">
          <select
            value={country}
            onChange={(e) => setCountry(e.target.value)}
            className="sort-select"
            style={{ fontSize: "12px", padding: "4px 8px" }}
            title="Search region"
          >
            {COUNTRIES.map((c) => (
              <option key={c.code} value={c.code}>{c.label}</option>
            ))}
          </select>
          <button className="nav-btn" onClick={() => setShowPricing(true)}>Pricing</button>
          <button className="nav-btn" onClick={() => setView("marketplace")}>Marketplace</button>
          {user && <button className="nav-btn" onClick={() => setView("library")}>Library</button>}
          {user && <button className="nav-btn" onClick={() => setView("purchases")}>Purchases</button>}
          {user && (user.tier === "maker" || user.tier === "pro" || user.tier === "admin") && (
            <button className="nav-btn" onClick={() => setView("dashboard")}>Seller</button>
          )}
          {user && (user.tier === "pro" || user.tier === "admin") && (
            <button className="nav-btn" onClick={() => setShowBatch(true)}>Batch</button>
          )}
          {user && user.tier === "admin" && (
            <button className="nav-btn nav-btn-admin" onClick={() => setView("admin")}>Admin</button>
          )}
          {user ? (
            <div className="user-info">
              <span className="user-name">{user.username}</span>
              <span className="user-tier">{user.tier}</span>
              <button className="nav-btn" onClick={handleLogout}>Sign Out</button>
            </div>
          ) : (
            <button className="btn btn-primary" onClick={() => setShowAuth(true)}>Sign In</button>
          )}
        </nav>
      </header>

      <div className="main-content">
        <button
          className="mobile-panel-toggle"
          onClick={() => setPanelCollapsed(!panelCollapsed)}
        >
          {panelCollapsed ? "Show Controls" : "Hide Controls"}
        </button>

        <div className={`panel-left${panelCollapsed ? " collapsed" : ""}`}>
          <SearchPanel onSelect={handleSelect} selectedResult={selectedResult} country={country} />

          {/* Pin Drop for Name Sign — mark a home or special location */}
          {config.productType === "name_sign" && (
            <div className="pin-drop-section" style={{
              background: "var(--bg-secondary, #1e1e2e)",
              border: "1px solid var(--border, #333)",
              borderRadius: "6px",
              padding: "12px",
              marginTop: "8px",
            }}>
              <h3 style={{ margin: "0 0 8px", fontSize: "13px", color: "var(--text-secondary, #aaa)" }}>
                Drop a Pin — Mark Your Location
              </h3>
              <p style={{ margin: "0 0 8px", fontSize: "11px", color: "var(--text-muted, #888)" }}>
                Enter coordinates for a home, cabin, or special place. The map will generate a board centered on this spot with a pin marker.
              </p>
              <div style={{ display: "flex", gap: "8px", marginBottom: "8px" }}>
                <div style={{ flex: 1 }}>
                  <label style={{ fontSize: "11px", color: "var(--text-secondary, #aaa)" }}>Latitude</label>
                  <input
                    type="number"
                    step="0.0001"
                    placeholder="45.4215"
                    className="search-input"
                    style={{ fontSize: "12px", padding: "6px 8px" }}
                    value={pinCoords?.lat ?? ""}
                    onChange={(e) => {
                      const lat = parseFloat(e.target.value);
                      setPinCoords((prev) => ({ lon: prev?.lon || 0, lat: isNaN(lat) ? 0 : lat }));
                    }}
                  />
                </div>
                <div style={{ flex: 1 }}>
                  <label style={{ fontSize: "11px", color: "var(--text-secondary, #aaa)" }}>Longitude</label>
                  <input
                    type="number"
                    step="0.0001"
                    placeholder="-75.6972"
                    className="search-input"
                    style={{ fontSize: "12px", padding: "6px 8px" }}
                    value={pinCoords?.lon ?? ""}
                    onChange={(e) => {
                      const lon = parseFloat(e.target.value);
                      setPinCoords((prev) => ({ lat: prev?.lat || 0, lon: isNaN(lon) ? 0 : lon }));
                    }}
                  />
                </div>
              </div>
              {pinCoords && pinCoords.lat !== 0 && (
                <MapPreview
                  lat={pinCoords.lat}
                  lon={pinCoords.lon}
                  name={config.text || "Pin Location"}
                />
              )}
            </div>
          )}

          <hr className="section-divider" />

          {/* Undo/Redo bar */}
          <div style={{ display: "flex", gap: "6px", justifyContent: "flex-end" }}>
            <button
              className="btn btn-secondary"
              onClick={handleUndo}
              disabled={!canUndo}
              style={{ padding: "4px 10px", fontSize: "11px" }}
              title="Undo (Ctrl+Z)"
            >
              Undo
            </button>
            <button
              className="btn btn-secondary"
              onClick={handleRedo}
              disabled={!canRedo}
              style={{ padding: "4px 10px", fontSize: "11px" }}
              title="Redo (Ctrl+Shift+Z)"
            >
              Redo
            </button>
          </div>

          <CustomizePanel config={config} onChange={handleConfigChange} user={user} />

          <MarkersPanel markers={markers} onChange={setMarkers} />

          <hr className="section-divider" />

          {qualityWarning && (
            <div className="quality-warning" style={{
              background: "#2a2515",
              border: "1px solid #5a4a20",
              borderRadius: "6px",
              padding: "8px 12px",
              fontSize: "12px",
              color: "#e8d0a0",
              fontFamily: "var(--font-mono)",
            }}>
              {qualityWarning}
            </div>
          )}

          <ExportPanel
            result={result}
            onGenerate={handleGenerate}
            onDownload={handleDownload}
            onDownloadDXF={handleDownloadDXF}
            onDownloadThumbnail={handleDownloadThumbnail}
            onDownloadPrintPNG={handleDownloadPrintPNG}
            canGenerate={!!selectedResult || (config.productType === "name_sign" && !!pinCoords)}
            generating={generating}
            user={user}
            outputMode={config.outputMode}
          />
        </div>
        <div className="panel-right">
          <SVGPreview
            svgContent={svgContent}
            loading={generating}
            error={error}
            outputMode={config.outputMode}
            colorTheme={config.colorTheme}
          />
        </div>
      </div>

      {/* Mobile bottom tab bar */}
      <div className="mobile-tab-bar">
        <div className="mobile-tab-bar-inner">
          <button className={`mobile-tab${view === "main" ? " active" : ""}`} onClick={() => setView("main")}>
            <span className="mobile-tab-icon">&#9670;</span>
            Generate
          </button>
          <button className={`mobile-tab${view === "marketplace" ? " active" : ""}`} onClick={() => setView("marketplace")}>
            <span className="mobile-tab-icon">&#9733;</span>
            Market
          </button>
          {user && (
            <button className={`mobile-tab${view === "library" ? " active" : ""}`} onClick={() => setView("library")}>
              <span className="mobile-tab-icon">&#9776;</span>
              Library
            </button>
          )}
          {user ? (
            <button className="mobile-tab" onClick={handleLogout}>
              <span className="mobile-tab-icon">&#8594;</span>
              Sign Out
            </button>
          ) : (
            <button className="mobile-tab" onClick={() => setShowAuth(true)}>
              <span className="mobile-tab-icon">&#9679;</span>
              Sign In
            </button>
          )}
        </div>
      </div>

      {showAuth && <AuthModal onAuth={handleAuth} onClose={() => setShowAuth(false)} />}
      {showBatch && <BatchPanel config={config} onClose={() => setShowBatch(false)} />}
      {showPricing && <PricingModal user={user} onClose={() => setShowPricing(false)} onSubscribe={handleSubscribe} />}
    </div>
  );
}
