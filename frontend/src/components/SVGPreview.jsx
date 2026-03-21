import { useState, useRef, useCallback, useEffect, useMemo } from "react";

// Color theme definitions matching backend COLOR_THEMES
const THEME_COLOR_MAPS = {
  classic: {
    bg: "#f5f3ee",
    map: { "#2a2a2a": "#ece6d6", "#1a1a1a": "#2a2a2a", "#d4e6f1": "#8fb8d8", "#7fb3d3": "#6a9ec4", "#333333": "#2a2a2a", "#555555": "#777777", "#444444": "#555555", "#cccccc": "#d4ccb8", "#666666": "#555555" },
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
  blueprint: {
    bg: "#1a2744",
    map: { "#2a2a2a": "#1e3050", "#1a1a1a": "#e8eef6", "#d4e6f1": "#1a2744", "#7fb3d3": "#4a7ab5", "#333333": "#e8eef6", "#555555": "#a0b8d8", "#444444": "#c8d8ee", "#cccccc": "#2a3d5e", "#666666": "#8aa8d0" },
  },
  dark: {
    bg: "#0a0a0a",
    map: { "#2a2a2a": "#1a1a1a", "#1a1a1a": "#d0d0d0", "#d4e6f1": "#151515", "#7fb3d3": "#333333", "#333333": "#cccccc", "#555555": "#888888", "#444444": "#aaaaaa", "#cccccc": "#1a1a1a", "#666666": "#999999" },
  },
  engraving: {
    bg: "#f8f5ef",
    map: { "#2a2a2a": "#f0ebe0", "#1a1a1a": "#2a2520", "#d4e6f1": "#e8e0d4", "#7fb3d3": "#8a7e6e", "#333333": "#2a2520", "#555555": "#5a5048", "#444444": "#1a1510", "#cccccc": "#d8d0c4", "#666666": "#4a4038" },
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

export default function SVGPreview({ svgContent, loading, error, outputMode, colorTheme, show3D }) {
  const [zoom, setZoom] = useState(100);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [panStart, setPanStart] = useState({ x: 0, y: 0 });
  const containerRef = useRef(null);

  const isPrint = outputMode === "print";
  const theme = THEME_COLOR_MAPS[colorTheme] || THEME_COLOR_MAPS.classic;

  // Make SVG responsive for in-browser display. SVGs with physical mm units
  // (width="406.4mm") render at full physical size (~1536px) which overflows
  // the preview container. Replace with responsive attributes while keeping
  // the viewBox for correct aspect ratio.
  const displaySvg = useMemo(() => {
    if (!svgContent) return null;

    let svg = svgContent;

    // Make SVG responsive: replace mm dimensions with CSS-friendly values
    // The viewBox attribute preserves aspect ratio and internal coordinates
    svg = svg.replace(/width="[\d.]+mm"/, 'width="100%"');
    svg = svg.replace(/height="[\d.]+mm"/, 'height="auto"');

    // In print mode with a backend-generated print SVG, use as-is (already themed)
    if (isPrint && svg.includes('id="mat_border"')) return svg;

    // CNC mode — return as-is (no color remap needed)
    if (!isPrint) return svg;

    // Fallback: legacy CNC SVG shown in print mode — apply client-side remap
    return applyPrintColors(svg, colorTheme || "classic");
  }, [svgContent, isPrint, colorTheme]);

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
        <p>{isPrint ? "Generating print-ready map..." : "Generating CNC-ready SVG..."}</p>
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
        <div className="preview-empty-icon">&#9670;</div>
        <p>
          Search for a location and click
          <br />
          <strong>{isPrint ? "Generate Map" : "Generate SVG"}</strong> to preview
        </p>
        <p style={{ fontSize: "10px", color: "var(--text-muted)", marginTop: "4px" }}>
          {isPrint
            ? "Generate colorful street maps for Etsy & print shops"
            : "Canada, US, and Global locations supported"}
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
        className={show3D && !isPrint ? "carved-3d-preview" : ""}
        style={{
          transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom / 100})`,
          transformOrigin: "center center",
          transition: isPanning ? "none" : "transform 0.15s ease",
          ...(show3D && !isPrint ? {
            perspective: "800px",
            transformStyle: "preserve-3d",
          } : {}),
        }}
      >
        <div
          style={show3D && !isPrint ? {
            transform: "rotateX(15deg) rotateY(-5deg)",
            filter: "drop-shadow(4px 8px 12px rgba(0,0,0,0.4))",
            background: "linear-gradient(145deg, #d4a76a, #8b6914)",
            borderRadius: "4px",
            padding: "8px",
          } : {}}
          dangerouslySetInnerHTML={{ __html: displaySvg }}
        />
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
        {show3D && !isPrint && (
          <>
            <div className="preview-toolbar-divider" />
            <span className="preview-toolbar-badge" style={{ background: "#8b6914" }}>3D Preview</span>
          </>
        )}
      </div>
    </div>
  );
}
