export default function SVGPreview({ svgContent, loading, error }) {
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

  return (
    <div
      className="preview-container"
      dangerouslySetInnerHTML={{ __html: svgContent }}
    />
  );
}
