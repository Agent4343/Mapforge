import { useState, useRef, useCallback } from "react";

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

  if (loading) {
    return (
      <div className="loading-overlay">
        <div className="spinner" />
        <p>Generating CNC-ready SVG...</p>
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
          Search for a Canadian location
          <br />
          to generate a CNC-ready SVG
        </p>
      </div>
    );
  }

  const toolbarStyle = {
    display: "flex",
    alignItems: "center",
    gap: "12px",
    padding: "8px 12px",
    background: "rgba(0, 0, 0, 0.6)",
    borderRadius: "8px",
    position: "absolute",
    bottom: "16px",
    left: "50%",
    transform: "translateX(-50%)",
    zIndex: 10,
    color: "#fff",
    fontSize: "13px",
    userSelect: "none",
  };

  const buttonStyle = {
    background: "rgba(255, 255, 255, 0.15)",
    border: "1px solid rgba(255, 255, 255, 0.25)",
    borderRadius: "4px",
    color: "#fff",
    padding: "4px 10px",
    cursor: "pointer",
    fontSize: "12px",
    whiteSpace: "nowrap",
  };

  const sliderStyle = {
    width: "120px",
    cursor: "pointer",
  };

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
      <div style={toolbarStyle}>
        <input
          type="range"
          min={50}
          max={200}
          value={zoom}
          onChange={(e) => setZoom(Number(e.target.value))}
          style={sliderStyle}
          onMouseDown={(e) => e.stopPropagation()}
        />
        <span style={{ minWidth: "40px", textAlign: "center" }}>{zoom}%</span>
        <button
          type="button"
          style={buttonStyle}
          onClick={(e) => {
            e.stopPropagation();
            handleFitToView();
          }}
          onMouseDown={(e) => e.stopPropagation()}
        >
          Fit to View
        </button>
      </div>
    </div>
  );
}
