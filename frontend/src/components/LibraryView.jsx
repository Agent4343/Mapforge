import { useState, useEffect } from "react";
import { getLibrary, deleteLibraryFile, downloadSVG, downloadPrintPNG } from "../services/api.js";

export default function LibraryView({ onBack }) {
  const [files, setFiles] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState(null);

  async function loadLibrary() {
    setLoading(true);
    try {
      const data = await getLibrary(page, 20, { search: filter || undefined });
      setFiles(data.files);
      setTotal(data.total);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadLibrary();
  }, [page, filter]);

  async function handleDelete(fileId) {
    if (!confirm("Delete this file?")) return;
    try {
      await deleteLibraryFile(fileId);
      loadLibrary();
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleDownload(fileId, name, format) {
    try {
      let blob;
      if (format === "png") blob = await downloadPrintPNG(fileId);
      else blob = await downloadSVG(fileId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${name.replace(/\s+/g, "_").toLowerCase()}.${format}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div className="library-view">
      <div className="view-header">
        <button className="btn btn-secondary" onClick={onBack}>Back</button>
        <h2>Template Library</h2>
        <span className="stat-value">{total} files</span>
      </div>

      <input
        type="text"
        className="search-input"
        placeholder="Filter by name..."
        value={filter}
        onChange={(e) => { setFilter(e.target.value); setPage(1); }}
      />

      {error && <div className="error-message">{error}</div>}

      {loading ? (
        <div className="loading-overlay"><div className="spinner" /></div>
      ) : (
        <div className="library-grid">
          {files.map((f) => (
            <div key={f.id} className="library-card">
              <div className="library-card-header">
                <span className="result-type-badge">{f.product_type}</span>
                <span className="library-card-name">{f.location_name}</span>
              </div>
              <div className="library-card-meta">
                {f.board_width_mm}x{f.board_height_mm}mm &middot; {f.style} &middot; {f.node_count} nodes
                {f.is_listed && <span className="badge-listed">Listed</span>}
              </div>
              <div className="library-card-actions">
                <button className="btn btn-secondary" onClick={() => handleDownload(f.id, f.location_name, "svg")}>
                  SVG
                </button>
                <button className="btn btn-secondary" onClick={() => handleDownload(f.id, f.location_name, "png")}>
                  Print PNG
                </button>
                <button className="btn btn-secondary" onClick={() => handleDelete(f.id)}>
                  Delete
                </button>
              </div>
            </div>
          ))}
          {files.length === 0 && <p className="empty-state">No files yet. Generate your first SVG!</p>}
        </div>
      )}

      {total > 20 && (
        <div className="pagination">
          <button className="btn btn-secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>Prev</button>
          <span>Page {page} of {Math.ceil(total / 20)}</span>
          <button className="btn btn-secondary" disabled={page * 20 >= total} onClick={() => setPage(page + 1)}>Next</button>
        </div>
      )}
    </div>
  );
}
