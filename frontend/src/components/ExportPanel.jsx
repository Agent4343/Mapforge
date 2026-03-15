import { useState } from "react";
import { createListing } from "../services/api.js";

export default function ExportPanel({
  result,
  onGenerate,
  onDownload,
  onDownloadDXF,
  onDownloadThumbnail,
  canGenerate,
  generating,
  user,
}) {
  const [showListForm, setShowListForm] = useState(false);
  const [listTitle, setListTitle] = useState("");
  const [listPrice, setListPrice] = useState("9.99");
  const [listDesc, setListDesc] = useState("");
  const [listError, setListError] = useState(null);
  const [listing, setListing] = useState(false);

  async function handleList() {
    if (!result) return;
    setListing(true);
    setListError(null);
    try {
      await createListing(
        result.file_id,
        listTitle || result.location_name,
        Math.round(parseFloat(listPrice) * 100),
        listDesc,
        ""
      );
      setShowListForm(false);
      setListTitle("");
    } catch (err) {
      setListError(err.message);
    } finally {
      setListing(false);
    }
  }

  const canSell = user && (user.tier === "maker" || user.tier === "pro");

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
              Dims: <span className="stat-value">{result.dimensions_mm[0]}x{result.dimensions_mm[1]}mm</span>
            </span>
            <span>
              Nodes: <span className="stat-value">{result.node_count}</span>
            </span>
            <span>
              Paths: <span className="stat-value">{result.path_count}</span>
            </span>
          </div>

          <div className="export-buttons">
            <button className="btn btn-secondary" onClick={onDownload}>
              Download SVG
            </button>
            {result.dxf_available && (
              <button className="btn btn-secondary" onClick={onDownloadDXF}>
                Download DXF
              </button>
            )}
            {result.thumbnail_available && (
              <button className="btn btn-secondary" onClick={onDownloadThumbnail}>
                Download PNG Mockup
              </button>
            )}
          </div>

          {canSell && !showListForm && (
            <button
              className="btn btn-secondary btn-full"
              onClick={() => {
                setListTitle(result.location_name);
                setShowListForm(true);
              }}
              style={{ marginTop: 8 }}
            >
              List on Marketplace
            </button>
          )}

          {showListForm && (
            <div className="list-form">
              <div className="control-group">
                <label>Title</label>
                <input type="text" value={listTitle} onChange={(e) => setListTitle(e.target.value)} />
              </div>
              <div className="control-group">
                <label>Price (USD)</label>
                <input
                  type="number"
                  min="1.99"
                  max="99.99"
                  step="0.01"
                  value={listPrice}
                  onChange={(e) => setListPrice(e.target.value)}
                />
              </div>
              <div className="control-group">
                <label>Description</label>
                <input type="text" value={listDesc} onChange={(e) => setListDesc(e.target.value)} placeholder="Optional" />
              </div>
              {listError && <div className="error-message">{listError}</div>}
              <div className="export-buttons">
                <button className="btn btn-primary" onClick={handleList} disabled={listing}>
                  {listing ? "Listing..." : "List for Sale"}
                </button>
                <button className="btn btn-secondary" onClick={() => setShowListForm(false)}>
                  Cancel
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
