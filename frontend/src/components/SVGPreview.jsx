import { useState, useRef, useCallback, useEffect, useMemo } from "react";

// Color theme definitions matching backend COLOR_THEMES
const THEME_COLOR_MAPS = {
  classic: {
    bg: "#faf8f5",
    map: { "#2a2a2a": "#4a7c59", "#1a1a1a": "#2d5016", "#d4e6f1": "#6db3d4", "#7fb3d3": "#3a8fbf", "#333333": "#8b7355", "#555555": "#a89279", "#444444": "#5c4a32", "#cccccc": "#d4c5a9", "#666666": "#6b5b47" },
  },
  modern_dark: {
    bg: "#1a1a2e",
    map: { "#2a2a2a": "#2d3748", "#1a1a1a": "#4a5568", "#d4e6f1": "#2b6cb0", "#7fb3d3": "#3182ce", "#333333": "#e2e8f0", "#555555": "#a0aec0", "#444444": "#cbd5e0", "#cccccc": "#2d3748", "#666666": "#a0aec0" },
  },
  rose_gold: {
    bg: "#fdf2f0",
    map: { "#2a2a2a": "#d4a59a", "#1a1a1a": "#c08b7f", "#d4e6f1": "#b8d4e3", "#7fb3d3": "#7ca8c4", "#333333": "#8b6f66", "#555555": "#a89080", "#444444": "#6b5550", "#cccccc": "#e8d5cf", "#666666": "#8b6f66" },
  },
  midnight: {
    bg: "#0f1923",
    map: { "#2a2a2a": "#1b3a4b", "#1a1a1a": "#3d7ea6", "#d4e6f1": "#1a4971", "#7fb3d3": "#2980b9", "#333333": "#c9d6df", "#555555": "#8fa7b8", "#444444": "#a8c4d4", "#cccccc": "#1b3a4b", "#666666": "#8fa7b8" },
  },
  sage: {
    bg: "#f5f7f2",
    map: { "#2a2a2a": "#7d9b76", "#1a1a1a": "#5a7a52", "#d4e6f1": "#a3c4bc", "#7fb3d3": "#6b9e91", "#333333": "#4a5e44", "#555555": "#6b7f65", "#444444": "#3d4e38", "#cccccc": "#c5d3be", "#666666": "#5a6e54" },
  },
  minimal: {
    bg: "#ffffff",
    map: { "#2a2a2a": "#e0e0e0", "#1a1a1a": "#333333", "#d4e6f1": "#f0f0f0", "#7fb3d3": "#999999", "#333333": "#222222", "#555555": "#666666", "#444444": "#444444", "#cccccc": "#e8e8e8", "#666666": "#888888" },
  },
  navy_gold: {
    bg: "#0a1628",
    map: { "#2a2a2a": "#1a2d52", "#1a1a1a": "#d4a843", "#d4e6f1": "#1a3a5c", "#7fb3d3": "#2c5f8a", "#333333": "#d4a843", "#555555": "#b8943a", "#444444": "#e8c95a", "#cccccc": "#1a2d52", "#666666": "#c9b06b" },
  },
  blush: {
    bg: "#fef0f0",
    map: { "#2a2a2a": "#e8b4b4", "#1a1a1a": "#c27c7c", "#d4e6f1": "#f0d4d4", "#7fb3d3": "#d4a0a0", "#333333": "#c27c7c", "#555555": "#d4a0a0", "#444444": "#8b5e5e", "#cccccc": "#f0d4d4", "#666666": "#a87070" },
  },
  ocean: {
    bg: "#e8f4f8",
    map: { "#2a2a2a": "#5dade2", "#1a1a1a": "#1a5276", "#d4e6f1": "#85c1e9", "#7fb3d3": "#3498db", "#333333": "#1a5276", "#555555": "#2980b9", "#444444": "#0e3d5c", "#cccccc": "#aed6f1", "#666666": "#1a5276" },
  },
  charcoal: {
    bg: "#2d2d2d",
    map: { "#2a2a2a": "#4a4a4a", "#1a1a1a": "#e0d5c1", "#d4e6f1": "#3d3d3d", "#7fb3d3": "#5a5a5a", "#333333": "#e0d5c1", "#555555": "#b8a88a", "#444444": "#d4c5a9", "#cccccc": "#4a4a4a", "#666666": "#c4b896" },
  },
  terracotta: {
    bg: "#faf0e6",
    map: { "#2a2a2a": "#cd7f50", "#1a1a1a": "#8b4513", "#d4e6f1": "#deb887", "#7fb3d3": "#b87333", "#333333": "#8b4513", "#555555": "#a0522d", "#444444": "#6b3410", "#cccccc": "#deb887", "#666666": "#8b5e3c" },
  },
  lavender: {
    bg: "#f3f0ff",
    map: { "#2a2a2a": "#b8a9d4", "#1a1a1a": "#5b4a8a", "#d4e6f1": "#d4ccf0", "#7fb3d3": "#9b8ec0", "#333333": "#5b4a8a", "#555555": "#7b6ba0", "#444444": "#3d2e6b", "#cccccc": "#d4ccf0", "#666666": "#6b5a9a" },
  },
  forest: {
    bg: "#0d1f0d",
    map: { "#2a2a2a": "#1a4a1a", "#1a1a1a": "#c4b896", "#d4e6f1": "#1a3a1a", "#7fb3d3": "#2d6b2d", "#333333": "#c4b896", "#555555": "#a0956b", "#444444": "#d4c5a0", "#cccccc": "#1a4a1a", "#666666": "#b8a882" },
  },
  sunset: {
    bg: "#fff5eb",
    map: { "#2a2a2a": "#e67e22", "#1a1a1a": "#c0392b", "#d4e6f1": "#f5cba7", "#7fb3d3": "#e59866", "#333333": "#c0392b", "#555555": "#d35400", "#444444": "#922b21", "#cccccc": "#f5cba7", "#666666": "#a93226" },
  },
  arctic: {
    bg: "#f0f8ff",
    map: { "#2a2a2a": "#85c1e9", "#1a1a1a": "#2c3e50", "#d4e6f1": "#d6eaf8", "#7fb3d3": "#5dade2", "#333333": "#2c3e50", "#555555": "#34495e", "#444444": "#1a252f", "#cccccc": "#aed6f1", "#666666": "#2c3e50" },
  },
};

function applyPrintColors(svg, themeName) {
  if (!svg || !themeName) return svg;
  const theme = THEME_COLOR_MAPS[themeName];
  if (!theme) return svg;

  let result = svg;
  for (const [oldColor, newColor] of Object.entries(theme.map)) {
    // Replace fill and stroke colors
    result = result.replaceAll(`fill="${oldColor}"`, `fill="${newColor}"`);
    result = result.replaceAll(`stroke="${oldColor}"`, `stroke="${newColor}"`);
  }
  return result;
}

export default function SVGPreview({ svgContent, loading, error, colorTheme }) {
  const [zoom, setZoom] = useState(100);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [panStart, setPanStart] = useState({ x: 0, y: 0 });
  const containerRef = useRef(null);

  const isPrint = true; // Always print/poster mode
  const theme = THEME_COLOR_MAPS[colorTheme] || THEME_COLOR_MAPS.classic;

  // Make SVG responsive for in-browser display. SVGs with physical mm units
  // (width="406.4mm") render at full physical size (~1536px) which overflows
  // the preview container. Replace with responsive attributes while keeping
  // the viewBox for correct aspect ratio.
  // Check if content is a PNG data URI (MapTiler poster) vs SVG markup
  const isImageDataUri = svgContent && svgContent.startsWith("data:image/");

  const displaySvg = useMemo(() => {
    if (!svgContent || isImageDataUri) return null;

    let svg = svgContent;

    // Make SVG responsive: set width to 100% and remove fixed height
    // so the viewBox attribute controls aspect ratio naturally
    svg = svg.replace(/width="[\d.]+mm"/, 'width="100%"');
    svg = svg.replace(/height="[\d.]+mm"/, '');

    // In print mode with a backend-generated print SVG, use as-is (already themed)
    if (isPrint && svg.includes('id="mat_border"')) return svg;

    // Return as-is if no color remap needed
    if (!isPrint) return svg;

    // Fallback: apply client-side color remap for older SVGs
    return applyPrintColors(svg, colorTheme || "classic");
  }, [svgContent, isPrint, colorTheme, isImageDataUri]);

  const handleMouseDown = useCallback(
    (e) => {
      setIsPanning(true);
      setPanStart({ x: e.clientX - pan.x, y: e.clientY - pan.y });
    },
    [pan]
  );

  const handleMouseMove = useCallback(
    (e) => {
      if (!isPanning) return;
      setPan({ x: e.clientX - panStart.x, y: e.clientY - panStart.y });
    },
    [isPanning, panStart]
  );

  const handleMouseUp = useCallback(() => {
    setIsPanning(false);
  }, []);

  const handleFitToView = () => {
    setZoom(100);
    setPan({ x: 0, y: 0 });
  };

  // Keyboard zoom: +/- keys and Ctrl+scroll
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    function handleWheel(e) {
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        const delta = e.deltaY > 0 ? -10 : 10;
        setZoom((z) => Math.min(300, Math.max(25, z + delta)));
      }
    }

    function handleKeyDown(e) {
      if (e.key === "=" || e.key === "+") {
        setZoom((z) => Math.min(300, z + 10));
      } else if (e.key === "-") {
        setZoom((z) => Math.max(25, z - 10));
      } else if (e.key === "0") {
        handleFitToView();
      }
    }

    el.addEventListener("wheel", handleWheel, { passive: false });
    el.addEventListener("keydown", handleKeyDown);
    el.setAttribute("tabindex", "0");

    return () => {
      el.removeEventListener("wheel", handleWheel);
      el.removeEventListener("keydown", handleKeyDown);
    };
  }, []);

  if (loading) {
    return (
      <div className="loading-overlay">
        <div className="spinner" />
        <p>Generating print-ready map...</p>
        <p style={{ fontSize: "10px", color: "var(--text-muted)" }}>
          Fetching geometry, streets, and water features...
        </p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="loading-overlay">
        <div className="error-message">{error}</div>
      </div>
    );
  }

  if (!svgContent) {
    return (
      <div className="preview-empty">
        <div className="preview-empty-icon" style={{ fontSize: "36px", opacity: 0.2 }}>
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/>
            <circle cx="12" cy="10" r="3"/>
          </svg>
        </div>
        <p>
          Search for a location and click
          <br />
          <strong>Generate Map</strong> to preview
        </p>
        <p style={{ fontSize: "10px", color: "var(--text-muted)", marginTop: "4px" }}>
          Street maps for Etsy, print shops &amp; wall art
        </p>
      </div>
    );
  }

  return (
    <div
      className="preview-container"
      ref={containerRef}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
      style={{
        position: "relative",
        overflow: "hidden",
        cursor: isPanning ? "grabbing" : "grab",
        background: isPrint ? theme.bg : undefined,
      }}
    >
      <div
        style={{
          transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom / 100})`,
          transformOrigin: "center center",
          transition: isPanning ? "none" : "transform 0.15s ease",
        }}
      >
        {isImageDataUri ? (
          <img
            src={svgContent}
            alt="Map poster"
            style={{ width: "100%", height: "auto", display: "block" }}
            draggable={false}
          />
        ) : (
          <div dangerouslySetInnerHTML={{ __html: displaySvg }} />
        )}
      </div>
      {/* Toolbar - positioned above the preview */}
      <div className="preview-toolbar">
        <button
          type="button"
          className="preview-toolbar-btn"
          onClick={(e) => { e.stopPropagation(); setZoom((z) => Math.max(25, z - 25)); }}
          onMouseDown={(e) => e.stopPropagation()}
          title="Zoom out (-)"
        >
          &minus;
        </button>
        <input
          type="range"
          min={25}
          max={300}
          value={zoom}
          onChange={(e) => setZoom(Number(e.target.value))}
          className="preview-zoom-slider"
          onMouseDown={(e) => e.stopPropagation()}
        />
        <span className="preview-zoom-label">{zoom}%</span>
        <button
          type="button"
          className="preview-toolbar-btn"
          onClick={(e) => { e.stopPropagation(); setZoom((z) => Math.min(300, z + 25)); }}
          onMouseDown={(e) => e.stopPropagation()}
          title="Zoom in (+)"
        >
          +
        </button>
        <div className="preview-toolbar-divider" />
        <button
          type="button"
          className="preview-toolbar-btn"
          onClick={(e) => {
            e.stopPropagation();
            handleFitToView();
          }}
          onMouseDown={(e) => e.stopPropagation()}
          title="Reset view (0)"
        >
          Fit
        </button>
        {isPrint && (
          <>
            <div className="preview-toolbar-divider" />
            <span className="preview-toolbar-badge">Print Preview</span>
          </>
        )}
      </div>
    </div>
  );
}
