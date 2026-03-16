import { useState, useCallback, useEffect, useRef } from "react";
import SearchPanel from "./components/SearchPanel.jsx";
import CustomizePanel from "./components/CustomizePanel.jsx";
import SVGPreview from "./components/SVGPreview.jsx";
import ExportPanel from "./components/ExportPanel.jsx";
import AuthModal from "./components/AuthModal.jsx";
import LibraryView from "./components/LibraryView.jsx";
import MarketplaceView from "./components/MarketplaceView.jsx";
import SellerDashboard from "./components/SellerDashboard.jsx";
import BatchPanel from "./components/BatchPanel.jsx";
import {
  generateSVG, downloadSVG, downloadDXF, downloadThumbnail,
  getProfile, logout, getToken,
} from "./services/api.js";

const DEFAULT_CONFIG = {
  text: "",
  boardSize: "medium",
  customWidth: 16,
  customHeight: 20,
  style: "outline",
  exportFormat: "svg",
  productType: "lake",
  fontSize: 14,
  showCoordinates: true,
  includeIslands: true,
  includeStreets: false,
  includeContours: false,
  contourType: "depth",
  numDepthBands: 5,
};

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
  const [view, setView] = useState("main"); // main, library, marketplace, dashboard

  const [selectedResult, setSelectedResult] = useState(null);
  const [config, setConfig] = useState(DEFAULT_CONFIG);
  const [svgContent, setSvgContent] = useState(null);
  const [result, setResult] = useState(null);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState(null);
  const [qualityWarning, setQualityWarning] = useState(null);
  const [country, setCountry] = useState("ca");
  const [panelCollapsed, setPanelCollapsed] = useState(false);

  // Undo/redo state
  const [configHistory, setConfigHistory] = useState([DEFAULT_CONFIG]);
  const [historyIndex, setHistoryIndex] = useState(0);
  const skipHistory = useRef(false);

  // Load user profile if token exists
  useEffect(() => {
    if (getToken()) {
      getProfile().then((p) => { if (p) setUser(p); });
    }
  }, []);

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
    if (!selectedResult) return;

    setGenerating(true);
    setError(null);
    setSvgContent(null);
    setResult(null);

    try {
      const params = {
        osm_id: selectedResult.osm_id,
        osm_type: selectedResult.osm_type,
        product_type: config.productType,
        board_size: config.boardSize,
        style: config.style,
        export_format: config.exportFormat,
        text: config.text,
        show_coordinates: config.showCoordinates,
        font_size_mm: config.fontSize,
        simplification: "auto",
        include_islands: config.includeIslands,
        min_island_area_m2: 5000,
        include_streets: config.includeStreets,
        include_contours: config.includeContours,
        contour_type: config.contourType,
        num_depth_bands: config.numDepthBands,
      };

      // Custom board dimensions
      if (config.boardSize === "custom") {
        params.board_width_inches = config.customWidth || 16;
        params.board_height_inches = config.customHeight || 20;
      }

      const data = await generateSVG(params);
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
  }, [selectedResult, config]);

  const handleDownload = useCallback(async () => {
    if (!result) return;
    try {
      const blob = await downloadSVG(result.file_id);
      _triggerDownload(blob, config.text, "svg");
    } catch (err) {
      setError(err.message);
    }
  }, [result, config.text]);

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

  // Sub-views
  if (view === "library") return <LibraryView onBack={() => setView("main")} />;
  if (view === "marketplace") return <MarketplaceView user={user} onBack={() => setView("main")} />;
  if (view === "dashboard") return <SellerDashboard onBack={() => setView("main")} />;

  const canUndo = historyIndex > 0;
  const canRedo = historyIndex < configHistory.length - 1;

  return (
    <div className="app">
      <header className="header">
        <div className="header-brand">
          <div>
            <h1>Map<span>Forge</span> CNC</h1>
            <div className="subtitle">Geographic SVG Generator for CNC Routing</div>
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
          <button className="nav-btn" onClick={() => setView("marketplace")}>Marketplace</button>
          {user && <button className="nav-btn" onClick={() => setView("library")}>Library</button>}
          {user && (user.tier === "maker" || user.tier === "pro" || user.tier === "admin") && (
            <button className="nav-btn" onClick={() => setView("dashboard")}>Seller</button>
          )}
          {user && (user.tier === "pro" || user.tier === "admin") && (
            <button className="nav-btn" onClick={() => setShowBatch(true)}>Batch</button>
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
            canGenerate={!!selectedResult}
            generating={generating}
            user={user}
          />
        </div>
        <div className="panel-right">
          <SVGPreview svgContent={svgContent} loading={generating} error={error} />
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
    </div>
  );
}
