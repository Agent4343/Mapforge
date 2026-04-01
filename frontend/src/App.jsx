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
import PriceDisplay from "./components/PriceDisplay.jsx";
import GenerateModal from "./components/CheckoutModal.jsx";
import OrderStatus from "./components/OrderStatus.jsx";
import {
  generateSVG, generatePin, downloadSVG, downloadDXF, downloadSTL,
  downloadThumbnail, downloadPrintPNG,
  downloadEtsyListing, downloadEtsyPackage, downloadPreview, downloadWallMockup,
  getProfile, logout, getToken, subscribe,
  redeemCredit,
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
  includeStreets: false,
  includeContours: false,
  contourType: "depth",
  numDepthBands: 5,
  outputMode: "print",
  colorTheme: "classic",
  posterLayout: "classic",
  heartLat: null,
  heartLon: null,
  showCompass: false,
  showScaleBar: false,
  gradientWater: true,
  landShadow: true,
  includeBleed: false,
  includeCropMarks: false,
  printDPI: 300,
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

const ETSY_DRAFT_STORAGE_KEY = "mapforge_etsy_drafts";
const MAX_ETSY_DRAFTS = 20;

function isFiniteCoordinate(value) {
  return typeof value === "number" && Number.isFinite(value);
}

function isValidLatitude(value) {
  return isFiniteCoordinate(value) && value >= -90 && value <= 90;
}

function isValidLongitude(value) {
  return isFiniteCoordinate(value) && value >= -180 && value <= 180;
}

function hasValidPinCoords(pinCoords) {
  if (!pinCoords) return false;
  return isValidLatitude(pinCoords.lat) && isValidLongitude(pinCoords.lon);
}

function parseCoordinateInput(rawValue) {
  if (rawValue === "") return null;
  const parsed = Number(rawValue);
  return Number.isFinite(parsed) ? parsed : null;
}

function createDraftId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `draft-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function createDesignRef() {
  return `MF-${Math.random().toString(36).slice(2, 8).toUpperCase()}`;
}

function readEtsyDraftStore() {
  try {
    const raw = localStorage.getItem(ETSY_DRAFT_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function writeEtsyDraftStore(store) {
  try {
    localStorage.setItem(ETSY_DRAFT_STORAGE_KEY, JSON.stringify(store));
  } catch {}
}

function saveEtsyDraft(payload) {
  const draftId = createDraftId();
  const designRef = createDesignRef();
  const store = readEtsyDraftStore();
  store[draftId] = {
    ...payload,
    draft_id: draftId,
    design_ref: designRef,
    updated_at: new Date().toISOString(),
  };

  const orderedDrafts = Object.entries(store)
    .sort(([, a], [, b]) => String(b?.updated_at || "").localeCompare(String(a?.updated_at || "")))
    .slice(0, MAX_ETSY_DRAFTS);

  writeEtsyDraftStore(Object.fromEntries(orderedDrafts));
  return { draftId, designRef };
}

function loadEtsyDraft(draftId) {
  const store = readEtsyDraftStore();
  return store[draftId] || null;
}

function listEtsyDrafts() {
  return Object.values(readEtsyDraftStore())
    .filter((draft) => draft && typeof draft === "object")
    .sort((a, b) => String(b?.updated_at || "").localeCompare(String(a?.updated_at || "")));
}

function deleteEtsyDraft(draftId) {
  const store = readEtsyDraftStore();
  if (!store[draftId]) return false;
  delete store[draftId];
  writeEtsyDraftStore(store);
  return true;
}

function formatDraftTime(isoTimestamp) {
  if (!isoTimestamp) return "saved recently";
  const date = new Date(isoTimestamp);
  if (Number.isNaN(date.getTime())) return "saved recently";
  const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  if (seconds < 60) return "saved just now";
  if (seconds < 3600) return `saved ${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `saved ${Math.floor(seconds / 3600)}h ago`;
  return `saved ${Math.floor(seconds / 86400)}d ago`;
}

// Toast notification system
function Toast({ message, type, onDismiss }) {
  useEffect(() => {
    const timer = setTimeout(onDismiss, 4000);
    return () => clearTimeout(timer);
  }, [onDismiss]);

  return (
    <div className={`toast toast-${type}`} onClick={onDismiss}>
      {message}
    </div>
  );
}

function ToastContainer({ toasts, onDismiss }) {
  return (
    <div className="toast-container">
      {toasts.map((t) => (
        <Toast key={t.id} message={t.message} type={t.type} onDismiss={() => onDismiss(t.id)} />
      ))}
    </div>
  );
}

let toastId = 0;

export default function App() {
  const [user, setUser] = useState(null);
  const [showAuth, setShowAuth] = useState(false);
  const [showBatch, setShowBatch] = useState(false);
  const [showPricing, setShowPricing] = useState(false);
  const [showLanding, setShowLanding] = useState(!getToken());
  const [view, setView] = useState("main"); // main, library, marketplace, dashboard
  const [toasts, setToasts] = useState([]);

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
  const [showGenerateModal, setShowGenerateModal] = useState(false);
  const [creditToken, setCreditToken] = useState(null); // design credit token from Etsy purchase
  const [creditData, setCreditData] = useState(null); // credit info from API
  const [creditView, setCreditView] = useState(null); // "status" to show order status page
  const [isEtsyReferral, setIsEtsyReferral] = useState(false);
  const [etsyDrafts, setEtsyDrafts] = useState([]);

  // Undo/redo state
  const [configHistory, setConfigHistory] = useState([config]);
  const [historyIndex, setHistoryIndex] = useState(0);
  const skipHistory = useRef(false);

  const addToast = useCallback((message, type = "error") => {
    const id = ++toastId;
    setToasts((prev) => [...prev.slice(-4), { id, message, type }]);
  }, []);

  const dismissToast = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  function loadRecentEtsyDrafts() {
    setEtsyDrafts(listEtsyDrafts().slice(0, 5));
  }

  function restoreDraftState(draft, { showToast = false } = {}) {
    if (!draft?.config) return false;
    const restoredConfig = { ...DEFAULT_CONFIG, ...draft.config };
    setShowLanding(false);
    setIsEtsyReferral(true);
    setConfig(restoredConfig);
    setConfigHistory([restoredConfig]);
    setHistoryIndex(0);
    setSelectedResult(draft.selectedResult || null);
    setPinCoords(draft.pinCoords || null);
    setMarkers(Array.isArray(draft.markers) ? draft.markers : []);
    setSvgContent(null);
    setResult(null);
    setError(null);
    setQualityWarning(null);
    if (showToast) {
      addToast(
        draft.design_ref ? `Restored your Etsy design (${draft.design_ref}).` : "Restored your Etsy design.",
        "success"
      );
    }
    return true;
  }

  function handleRestoreEtsyDraft(draftId) {
    const draft = loadEtsyDraft(draftId);
    if (!restoreDraftState(draft, { showToast: true })) {
      addToast("Could not restore that draft.", "error");
    }
    loadRecentEtsyDrafts();
  }

  function handleDeleteEtsyDraft(draftId) {
    if (deleteEtsyDraft(draftId)) {
      addToast("Draft removed.", "success");
      loadRecentEtsyDrafts();
    }
  }

  useEffect(() => {
    loadRecentEtsyDrafts();
  }, []);

  // Load user profile if token exists; clear stale tokens on failure
  useEffect(() => {
    if (getToken()) {
      getProfile()
        .then((p) => { if (p) setUser(p); else { logout(); } })
        .catch(() => { logout(); });
    }
  }, []);

  // Fetch public config (Etsy shop URL, etc.)
  const [etsyShopUrl, setEtsyShopUrl] = useState(null);
  useEffect(() => {
    fetch(`${import.meta.env.VITE_API_URL || ""}/api/v1/config`)
      .then((r) => r.json())
      .then((c) => { if (c.etsy_shop_url) setEtsyShopUrl(c.etsy_shop_url); })
      .catch(() => {});
  }, []);

  // Handle URL params: Etsy design credits (?credit=TOKEN) and referrals (?ref=etsy)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);

    // Etsy purchase credit — customer bought on Etsy, has a design token
    const creditParam = params.get("credit");
    if (creditParam) {
      setCreditToken(creditParam);
      setShowLanding(false);
      setIsEtsyReferral(true);
      window.history.replaceState({}, "", window.location.pathname);
      // Validate the token
      redeemCredit(creditParam)
        .then((data) => {
          setCreditData(data);
          // If already completed, show the download page
          if (data.status === "completed" || data.status === "generating") {
            setCreditView("status");
          }
          // Pre-fill product type from the Etsy listing
          if (data.product_type) {
            setConfig((prev) => ({ ...prev, productType: data.product_type }));
          }
        })
        .catch(() => {
          setCreditToken(null);
          setCreditData(null);
        });
      return;
    }

    let shouldClearQuery = false;
    let restoredFromDraft = false;

    // Restore draft when returning from Etsy with a saved draft ID
    const draftParam = params.get("draft");
    if (draftParam) {
      shouldClearQuery = true;
      const draft = loadEtsyDraft(draftParam);
      restoredFromDraft = restoreDraftState(draft, { showToast: true });
    }

    // Etsy OAuth callback success
    if (params.get("etsy_connected") === "1") {
      shouldClearQuery = true;
      addToast("Etsy shop connected! Generate a map and publish it to your shop.", "success");
    }

    // Etsy OAuth callback error
    const etsyError = params.get("etsy_error");
    if (etsyError) {
      shouldClearQuery = true;
      addToast(`Etsy connection failed: ${etsyError}. Please try again.`, "error");
    }

    // Etsy referral (no credit yet — just browsing from listing description)
    if (params.get("ref") === "etsy") {
      shouldClearQuery = true;
      setIsEtsyReferral(true);
      setShowLanding(false);
      if (!restoredFromDraft) {
        const updates = {};
        if (params.get("product_type")) updates.productType = params.get("product_type");
        if (params.get("board_size")) updates.boardSize = params.get("board_size");
        if (params.get("color_theme")) updates.colorTheme = params.get("color_theme");
        if (Object.keys(updates).length > 0) {
          setConfig((prev) => ({ ...prev, ...updates }));
        }
      }
    }

    if (shouldClearQuery) {
      window.history.replaceState({}, "", window.location.pathname);
    }
    loadRecentEtsyDrafts();
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
      addToast(err.message, "error");
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

    // Check geometry quality and search confidence before generation.
    if (!item.has_geometry && item.fallback_available) {
      setQualityWarning(
        "This location has no exact boundary, but MapForge can use fallback area mode. For highest accuracy, prefer a Best Match with medium/high geometry."
      );
    } else if (!item.has_geometry) {
      setQualityWarning("This location may not have polygon data. Generation might fail or produce incomplete results.");
    } else if (item.geometry_quality === "low") {
      setQualityWarning(
        "This match has low geometry detail and may look inaccurate. Try another result (prefer one marked Best Match / high geometry)."
      );
    } else if (item.match_confidence === "low") {
      setQualityWarning(
        "This match has low location confidence. If the preview looks wrong, choose a result with higher confidence."
      );
    } else {
      setQualityWarning(null);
    }
  }

  const handleGenerate = useCallback(async () => {
    // Pin-drop mode: use coordinates instead of OSM search result
    const isPinMode = config.productType === "name_sign" && hasValidPinCoords(pinCoords);
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
          style: "filled",
          export_format: "svg",
          show_coordinates: config.showCoordinates,
          font_size_mm: config.fontSize,
          font_family: config.fontFamily || "sans",
          border_style: config.borderStyle || "none",
          include_streets: config.includeStreets,
          output_mode: "print",
          color_theme: config.colorTheme || "classic",
          poster_layout: config.posterLayout || "classic",
          show_compass: config.showCompass || false,
          show_scale_bar: config.showScaleBar || false,
          gradient_water: config.gradientWater !== false,
          land_shadow: config.landShadow !== false,
          include_bleed: config.includeBleed || false,
          include_crop_marks: config.includeCropMarks || false,
          print_dpi: config.printDPI || 300,
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
          style: "filled",
          export_format: "svg",
          output_mode: "print",
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
          poster_layout: config.posterLayout || "classic",
          heart_lat: config.heartLat || undefined,
          heart_lon: config.heartLon || undefined,
          show_compass: config.showCompass || false,
          show_scale_bar: config.showScaleBar || false,
          gradient_water: config.gradientWater !== false,
          land_shadow: config.landShadow !== false,
          include_bleed: config.includeBleed || false,
          include_crop_marks: config.includeCropMarks || false,
          print_dpi: config.printDPI || 300,
        };
        if (config.boardSize === "custom") {
          params.board_width_inches = config.customWidth || 16;
          params.board_height_inches = config.customHeight || 20;
        }
        data = await generateSVG(params);
      }

      setSvgContent(data.svg);
      setResult(data);

      // Quality/generation warnings
      const allWarnings = [...(data.warnings || [])];
      if (data.node_count < 20) {
        allWarnings.push("Low detail: This location has very few data points. The map may appear rough or oversimplified.");
      }
      if (data.needs_location_repick) {
        allWarnings.push(
          "Recommendation: re-pick another search result (prefer Best Match + medium/high geometry) before final purchase."
        );
      }
      setQualityWarning(allWarnings.length > 0 ? allWarnings.join(" ") : null);
    } catch (err) {
      setError(err.message);
    } finally {
      setGenerating(false);
    }
  }, [selectedResult, config, pinCoords, markers]);

  const handleDownload = useCallback(async () => {
    if (!result) return;
    try {
      const blob = await downloadSVG(result.file_id);
      _triggerDownload(blob, config.text, "svg");
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

  const handleDownloadDXF = useCallback(async () => {
    if (!result) return;
    try {
      const blob = await downloadDXF(result.file_id);
      _triggerDownload(blob, config.text + "_cnc", "dxf");
    } catch (err) {
      setError(err.message);
    }
  }, [result, config.text]);

  const handleDownloadSTL = useCallback(async () => {
    if (!result) return;
    try {
      const blob = await downloadSTL(result.file_id);
      _triggerDownload(blob, config.text + "_3d", "stl");
    } catch (err) {
      setError(err.message);
    }
  }, [result, config.text]);

  const handleDownloadEtsyListing = useCallback(async () => {
    if (!result) return;
    try {
      const blob = await downloadEtsyListing(result.file_id);
      _triggerDownload(blob, config.text + "_etsy_listing", "png");
    } catch (err) {
      setError(err.message);
    }
  }, [result, config.text]);

  const handleDownloadEtsyPackage = useCallback(async () => {
    if (!result) return;
    try {
      const blob = await downloadEtsyPackage(result.file_id);
      _triggerDownload(blob, config.text + "_etsy_package", "zip");
    } catch (err) {
      setError(err.message);
    }
  }, [result, config.text]);

  const handleDownloadPreview = useCallback(async () => {
    if (!result) return;
    try {
      const blob = await downloadPreview(result.file_id);
      _triggerDownload(blob, config.text + "_preview", "png");
    } catch (err) {
      setError(err.message);
    }
  }, [result, config.text]);

  const handleDownloadWallMockup = useCallback(async (style = "light_wall") => {
    if (!result) return;
    try {
      const blob = await downloadWallMockup(result.file_id, style);
      _triggerDownload(blob, config.text + "_wall_mockup_" + style, "png");
    } catch (err) {
      setError(err.message);
    }
  }, [result, config.text]);

  const handleStartEtsyCheckout = useCallback(() => {
    if (!etsyShopUrl) {
      addToast("Etsy shop link is not configured yet.", "error");
      return;
    }

    const selectedSnapshot = selectedResult
      ? {
          osm_id: selectedResult.osm_id,
          osm_type: selectedResult.osm_type,
          display_name: selectedResult.display_name,
          feature_type: selectedResult.feature_type,
          lat: selectedResult.lat,
          lon: selectedResult.lon,
          has_geometry: selectedResult.has_geometry,
          boundingbox: selectedResult.boundingbox,
        }
      : null;

    const { draftId, designRef } = saveEtsyDraft({
      source: "etsy_checkout_handoff",
      config,
      selectedResult: selectedSnapshot,
      pinCoords,
      markers,
      result: result
        ? {
            file_id: result.file_id,
            location_name: result.location_name,
            product_type: result.product_type,
            style: result.style,
          }
        : null,
    });
    loadRecentEtsyDrafts();

    const checkoutUrl = new URL(etsyShopUrl, window.location.origin);
    checkoutUrl.searchParams.set("ref", "mapforge_app");
    checkoutUrl.searchParams.set("draft", draftId);
    checkoutUrl.searchParams.set("design_ref", designRef);
    if (config.productType) checkoutUrl.searchParams.set("product_type", config.productType);
    if (config.boardSize) checkoutUrl.searchParams.set("board_size", config.boardSize);
    if (config.colorTheme) checkoutUrl.searchParams.set("color_theme", config.colorTheme);
    if (result?.location_name) checkoutUrl.searchParams.set("location", result.location_name);

    window.location.href = checkoutUrl.toString();
  }, [addToast, config, etsyShopUrl, markers, pinCoords, result, selectedResult]);

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

  // Order status page (after generation started or already completed)
  if (creditView === "status" && creditToken) {
    return (
      <div className="app">
        <header className="header">
          <div className="header-brand">
            <div>
              <h1>Map<span>Forge</span></h1>
              <div className="subtitle">Custom Map Art</div>
            </div>
          </div>
        </header>
        <div className="order-status-page">
          <OrderStatus
            creditToken={creditToken}
            onBack={() => { setCreditView(null); }}
          />
        </div>
      </div>
    );
  }

  // Landing page for new visitors (unless they came from Etsy)
  if (showLanding && !user && !isEtsyReferral) {
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
            <div className="subtitle">Custom Map Art — Design Yours</div>
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
          {user?.tier === "admin" && <button className="nav-btn" onClick={() => setShowPricing(true)}>Pricing</button>}
          {user?.tier === "admin" && <button className="nav-btn" onClick={() => setView("marketplace")}>Marketplace</button>}
          {user?.tier === "admin" && <button className="nav-btn" onClick={() => setView("library")}>Library</button>}
          {user?.tier === "admin" && <button className="nav-btn" onClick={() => setView("purchases")}>Purchases</button>}
          {user?.tier === "admin" && (
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
                      const lat = parseCoordinateInput(e.target.value);
                      setPinCoords((prev) => ({ lon: prev?.lon ?? null, lat }));
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
                      const lon = parseCoordinateInput(e.target.value);
                      setPinCoords((prev) => ({ lat: prev?.lat ?? null, lon }));
                    }}
                  />
                </div>
              </div>
              {pinCoords && !hasValidPinCoords(pinCoords) && (
                <p style={{ margin: "0 0 8px", fontSize: "11px", color: "var(--text-muted, #888)" }}>
                  Enter valid coordinates (latitude between -90 and 90, longitude between -180 and 180).
                </p>
              )}
              {hasValidPinCoords(pinCoords) && (
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

          {isEtsyReferral && !creditToken && (
            <div className="etsy-drafts-panel">
              <div className="etsy-drafts-header">
                <h3>Recent Etsy Drafts</h3>
                <button
                  className="link-btn"
                  type="button"
                  onClick={loadRecentEtsyDrafts}
                  style={{ fontSize: "11px" }}
                >
                  Refresh
                </button>
              </div>
              {etsyDrafts.length === 0 ? (
                <p className="etsy-drafts-empty">No saved Etsy drafts yet.</p>
              ) : (
                <div className="etsy-drafts-list">
                  {etsyDrafts.map((draft) => (
                    <div key={draft.draft_id} className="etsy-draft-item">
                      <div className="etsy-draft-main">
                        <div className="etsy-draft-title">
                          {draft.config?.text || draft.result?.location_name || "Untitled design"}
                        </div>
                        <div className="etsy-draft-meta">
                          {draft.design_ref ? `${draft.design_ref} · ` : ""}
                          {formatDraftTime(draft.updated_at)}
                        </div>
                      </div>
                      <div className="etsy-draft-actions">
                        <button
                          className="btn btn-secondary"
                          type="button"
                          style={{ fontSize: "10px", padding: "4px 8px" }}
                          onClick={() => handleRestoreEtsyDraft(draft.draft_id)}
                        >
                          Resume
                        </button>
                        <button
                          className="btn btn-secondary"
                          type="button"
                          style={{ fontSize: "10px", padding: "4px 8px" }}
                          onClick={() => handleDeleteEtsyDraft(draft.draft_id)}
                        >
                          Delete
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Etsy credit banner — show when customer has a valid design credit */}
          {creditToken && creditData && creditData.status === "unused" && (
            <div className="credit-banner">
              <div className="credit-banner-text">
                Etsy purchase confirmed — design your custom map below, then click Generate.
              </div>
            </div>
          )}

          {/* Generate button for Etsy customers with a credit */}
          {creditToken && creditData && creditData.status === "unused" &&
           (!!selectedResult || (config.productType === "name_sign" && hasValidPinCoords(pinCoords))) && (
            <button
              className="btn btn-primary btn-full checkout-cta"
              onClick={() => setShowGenerateModal(true)}
              style={{ marginBottom: "12px", fontSize: "16px", padding: "14px" }}
            >
              Generate My Map — Included with Etsy Purchase
            </button>
          )}

          {/* Price display for browsing customers (no credit yet) */}
          {!creditToken && (
            <PriceDisplay config={config} markers={markers} />
          )}

          <ExportPanel
            result={result}
            onGenerate={handleGenerate}
            onDownload={handleDownload}
            onDownloadDXF={handleDownloadDXF}
            onDownloadSTL={handleDownloadSTL}
            onDownloadThumbnail={handleDownloadThumbnail}
            onDownloadPrintPNG={handleDownloadPrintPNG}
            onDownloadEtsyListing={handleDownloadEtsyListing}
            onDownloadEtsyPackage={handleDownloadEtsyPackage}
            onDownloadPreview={handleDownloadPreview}
            onDownloadWallMockup={handleDownloadWallMockup}
            canGenerate={!!selectedResult || (config.productType === "name_sign" && hasValidPinCoords(pinCoords))}
            generating={generating}
            user={user}
            printDPI={config.printDPI}
            etsyShopUrl={etsyShopUrl}
            onStartEtsyCheckout={handleStartEtsyCheckout}
          />
        </div>
        <div className="panel-right">
          <SVGPreview
            svgContent={svgContent}
            loading={generating}
            error={error}
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
      {showGenerateModal && creditToken && (
        <GenerateModal
          config={config}
          selectedResult={selectedResult}
          pinCoords={pinCoords}
          markers={markers}
          creditToken={creditToken}
          onClose={() => setShowGenerateModal(false)}
          onGenerating={() => {
            setShowGenerateModal(false);
            setCreditView("status");
          }}
        />
      )}
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </div>
  );
}
