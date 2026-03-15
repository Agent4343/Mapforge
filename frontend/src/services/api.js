/**
 * MapForge CNC — API client
 */

const API_BASE = "/api/v1";

export async function searchLocations(query) {
  const resp = await fetch(
    `${API_BASE}/search?q=${encodeURIComponent(query)}&country=ca&limit=10`
  );
  if (!resp.ok) throw new Error(`Search failed: ${resp.statusText}`);
  return resp.json();
}

export async function generateSVG(params) {
  const resp = await fetch(`${API_BASE}/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(err.detail || "Generation failed");
  }
  return resp.json();
}

export async function downloadSVG(fileId) {
  const resp = await fetch(`${API_BASE}/download/${fileId}`);
  if (!resp.ok) throw new Error("Download failed");
  return resp.blob();
}
