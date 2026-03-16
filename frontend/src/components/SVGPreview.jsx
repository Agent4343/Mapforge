import { useState, useRef, useCallback, useEffect } from "react";

export default function SVGPreview({ svgContent, loading, error }) {
  const [zoom, setZoom] = useState(100);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [panStart, setPanStart] = useState({ x: 0, y: 0 });
  const containerRef = useRef(null);

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
        <p>Generating CNC-ready SVG...</p>
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
          <strong>Generate SVG</strong> to preview
        </p>
        <p style={{ fontSize: "10px", color: "var(--text-muted)", marginTop: "4px" }}>
          Canada, US, and Global locations supported
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
      }}
    >
      <div
        style={{
          transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom / 100})`,
          transformOrigin: "center center",
          transition: isPanning ? "none" : "transform 0.15s ease",
        }}
        dangerouslySetInnerHTML={{ __html: svgContent }}
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
      </div>
    </div>
  );
}
