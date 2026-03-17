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

export default function SVGPreview({ svgContent, loading, error, outputMode, colorTheme }) {
  const [zoom, setZoom] = useState(100);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [panStart, setPanStart] = useState({ x: 0, y: 0 });
  const containerRef = useRef(null);

  const isPrint = outputMode === "print";
  const theme = THEME_COLOR_MAPS[colorTheme] || THEME_COLOR_MAPS.classic;

  // Apply print colors to SVG when in print mode
  const displaySvg = useMemo(() => {
    if (!svgContent) return null;
    if (!isPrint) return svgContent;
    return applyPrintColors(svgContent, colorTheme || "classic");
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
        style={{
          transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom / 100})`,
          transformOrigin: "center center",
          transition: isPanning ? "none" : "transform 0.15s ease",
        }}
        dangerouslySetInnerHTML={{ __html: displaySvg }}
      />
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
