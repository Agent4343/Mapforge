import { useState, useCallback } from "react";
import SearchPanel from "./components/SearchPanel.jsx";
import CustomizePanel from "./components/CustomizePanel.jsx";
import SVGPreview from "./components/SVGPreview.jsx";
import ExportPanel from "./components/ExportPanel.jsx";
import { generateSVG, downloadSVG } from "./services/api.js";

const DEFAULT_CONFIG = {
  text: "",
  boardSize: "medium",
  style: "outline",
  productType: "lake",
  fontSize: 14,
  showCoordinates: true,
  includeIslands: true,
};

export default function App() {
  const [selectedResult, setSelectedResult] = useState(null);
  const [config, setConfig] = useState(DEFAULT_CONFIG);
  const [svgContent, setSvgContent] = useState(null);
  const [result, setResult] = useState(null);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState(null);

  function handleSelect(item) {
    setSelectedResult(item);
    const name = item.display_name.split(",")[0].trim();
    setConfig((prev) => ({
      ...prev,
      text: name,
      productType: item.feature_type || prev.productType,
    }));
    // Clear previous result when selecting new location
    setSvgContent(null);
    setResult(null);
    setError(null);
  }

  const handleGenerate = useCallback(async () => {
    if (!selectedResult) return;

    setGenerating(true);
    setError(null);
    setSvgContent(null);
    setResult(null);

    try {
      const data = await generateSVG({
        osm_id: selectedResult.osm_id,
        osm_type: selectedResult.osm_type,
        product_type: config.productType,
        board_size: config.boardSize,
        style: config.style,
        text: config.text,
        show_coordinates: config.showCoordinates,
        font_size_mm: config.fontSize,
        simplification: "auto",
        include_islands: config.includeIslands,
        min_island_area_m2: 5000,
      });

      setSvgContent(data.svg);
      setResult(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setGenerating(false);
    }
  }, [selectedResult, config]);

  const handleDownload = useCallback(async () => {
    if (!result) return;

    try {
      const blob = await downloadSVG(result.file_id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${config.text.replace(/\s+/g, "_").toLowerCase() || "mapforge"}.svg`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err.message);
    }
  }, [result, config.text]);

  return (
    <div className="app">
      <header className="header">
        <div className="header-brand">
          <div>
            <h1>
              Map<span>Forge</span> CNC
            </h1>
            <div className="subtitle">
              Canadian Geographic SVG Generator for CNC Routing
            </div>
          </div>
        </div>
      </header>

      <div className="main-content">
        <div className="panel-left">
          <SearchPanel
            onSelect={handleSelect}
            selectedResult={selectedResult}
          />

          <hr className="section-divider" />

          <CustomizePanel config={config} onChange={setConfig} />

          <hr className="section-divider" />

          <ExportPanel
            result={result}
            onGenerate={handleGenerate}
            onDownload={handleDownload}
            canGenerate={!!selectedResult}
            generating={generating}
          />
        </div>

        <div className="panel-right">
          <SVGPreview
            svgContent={svgContent}
            loading={generating}
            error={error}
          />
        </div>
      </div>
    </div>
  );
}
