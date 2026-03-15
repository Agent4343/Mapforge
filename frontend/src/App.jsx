import { useState, useCallback, useEffect } from "react";
import SearchPanel from "./components/SearchPanel.jsx";
import CustomizePanel from "./components/CustomizePanel.jsx";
import SVGPreview from "./components/SVGPreview.jsx";
import ExportPanel from "./components/ExportPanel.jsx";
import AuthModal from "./components/AuthModal.jsx";
import LibraryView from "./components/LibraryView.jsx";
import MarketplaceView from "./components/MarketplaceView.jsx";
import SellerDashboard from "./components/SellerDashboard.jsx";
import {
  generateSVG, downloadSVG, downloadDXF,
  getProfile, logout, getToken,
} from "./services/api.js";

const DEFAULT_CONFIG = {
  text: "",
  boardSize: "medium",
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

export default function App() {
  const [user, setUser] = useState(null);
  const [showAuth, setShowAuth] = useState(false);
  const [view, setView] = useState("main"); // main, library, marketplace, dashboard

  const [selectedResult, setSelectedResult] = useState(null);
  const [config, setConfig] = useState(DEFAULT_CONFIG);
  const [svgContent, setSvgContent] = useState(null);
  const [result, setResult] = useState(null);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState(null);

  // Load user profile if token exists
  useEffect(() => {
    if (getToken()) {
      getProfile().then((p) => { if (p) setUser(p); });
    }
  }, []);

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
    setConfig((prev) => ({
      ...prev,
      text: name,
      productType: item.feature_type || prev.productType,
    }));
    setSvgContent(null);
    setResult(null);
    setError(null);
  }

  const handleGenerate = useCallback(async () => {
    if (!selectedResult) return;

    setGenerating(true);
    setError(null);
    setSvgContent(null);
    setResult(null);

    try {
      const data = await generateSVG({
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
      });

      setSvgContent(data.svg);
      setResult(data);
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

  return (
    <div className="app">
      <header className="header">
        <div className="header-brand">
          <div>
            <h1>Map<span>Forge</span> CNC</h1>
            <div className="subtitle">Canadian Geographic SVG Generator for CNC Routing</div>
          </div>
        </div>
        <nav className="header-nav">
          <button className="nav-btn" onClick={() => setView("marketplace")}>Marketplace</button>
          {user && <button className="nav-btn" onClick={() => setView("library")}>Library</button>}
          {user && (user.tier === "maker" || user.tier === "pro") && (
            <button className="nav-btn" onClick={() => setView("dashboard")}>Seller</button>
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
        <div className="panel-left">
          <SearchPanel onSelect={handleSelect} selectedResult={selectedResult} />
          <hr className="section-divider" />
          <CustomizePanel config={config} onChange={setConfig} user={user} />
          <hr className="section-divider" />
          <ExportPanel
            result={result}
            onGenerate={handleGenerate}
            onDownload={handleDownload}
            onDownloadDXF={handleDownloadDXF}
            canGenerate={!!selectedResult}
            generating={generating}
            user={user}
          />
        </div>
        <div className="panel-right">
          <SVGPreview svgContent={svgContent} loading={generating} error={error} />
        </div>
      </div>

      {showAuth && <AuthModal onAuth={handleAuth} onClose={() => setShowAuth(false)} />}
    </div>
  );
}
