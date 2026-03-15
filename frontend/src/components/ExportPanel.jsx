export default function ExportPanel({ result, onGenerate, onDownload, canGenerate, generating }) {
  return (
    <div className="export-section">
      <h2>Export</h2>

      <button
        className="btn btn-primary btn-full"
        onClick={onGenerate}
        disabled={!canGenerate || generating}
      >
        {generating ? "Generating..." : "Generate SVG"}
      </button>

      {result && (
        <>
          <div className="file-stats">
            <span>
              Dims: <span className="stat-value">{result.dimensions_mm[0]}×{result.dimensions_mm[1]}mm</span>
            </span>
            <span>
              Nodes: <span className="stat-value">{result.node_count}</span>
            </span>
            <span>
              Paths: <span className="stat-value">{result.path_count}</span>
            </span>
          </div>

          <button className="btn btn-secondary btn-full" onClick={onDownload}>
            Download SVG File
          </button>
        </>
      )}
    </div>
  );
}
