/**
 * MapForge CNC — API client with auth support
 */

const API_BASE = "/api/v1";
const TIMEOUT_MS = 30000;

let authToken = localStorage.getItem("mapforge_token") || null;

function setToken(token) {
  authToken = token;
  if (token) {
    localStorage.setItem("mapforge_token", token);
  } else {
    localStorage.removeItem("mapforge_token");
  }
}

function getToken() {
  return authToken;
}

async function fetchWithTimeout(url, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), TIMEOUT_MS);

  const headers = { ...options.headers };
  if (authToken) {
    headers["Authorization"] = `Bearer ${authToken}`;
  }

  try {
    const resp = await fetch(url, { ...options, headers, signal: controller.signal });
    return resp;
  } finally {
    clearTimeout(timeout);
  }
}

// --- Auth ---

async function register(email, username, password) {
  const resp = await fetchWithTimeout(`${API_BASE}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, username, password }),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(err.detail || "Registration failed");
  }
  const data = await resp.json();
  setToken(data.access_token);
  return data;
}

async function login(email, password) {
  const resp = await fetchWithTimeout(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(err.detail || "Login failed");
  }
  const data = await resp.json();
  setToken(data.access_token);
  return data;
}

function logout() {
  setToken(null);
}

async function getProfile() {
  const resp = await fetchWithTimeout(`${API_BASE}/auth/me`);
  if (!resp.ok) return null;
  return resp.json();
}

// --- Search ---

async function searchLocations(query, country = "ca") {
  const resp = await fetchWithTimeout(
    `${API_BASE}/search?q=${encodeURIComponent(query)}&country=${encodeURIComponent(country)}&limit=10`
  );
  if (!resp.ok) throw new Error(`Search failed: ${resp.statusText}`);
  return resp.json();
}

// --- Generate ---

async function generateSVG(params) {
  const resp = await fetchWithTimeout(`${API_BASE}/generate`, {
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

async function generatePin(params) {
  const resp = await fetchWithTimeout(`${API_BASE}/generate/pin`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(err.detail || "Pin generation failed");
  }
  return resp.json();
}

async function batchGenerate(items) {
  const resp = await fetchWithTimeout(`${API_BASE}/generate/batch`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items }),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(err.detail || "Batch generation failed");
  }
  return resp.json();
}

// --- Download ---

async function downloadSVG(fileId) {
  const resp = await fetchWithTimeout(`${API_BASE}/download/${fileId}?format=svg`);
  if (!resp.ok) throw new Error("Download failed");
  return resp.blob();
}

async function downloadDXF(fileId) {
  const resp = await fetchWithTimeout(`${API_BASE}/download/${fileId}?format=dxf`);
  if (!resp.ok) throw new Error("DXF download failed");
  return resp.blob();
}

async function downloadThumbnail(fileId) {
  const resp = await fetchWithTimeout(`${API_BASE}/download/${fileId}/thumbnail`);
  if (!resp.ok) throw new Error("Thumbnail download failed");
  return resp.blob();
}

// --- Library ---

async function getLibrary(page = 1, perPage = 20, filters = {}) {
  const params = new URLSearchParams({ page, per_page: perPage });
  if (filters.product_type) params.set("product_type", filters.product_type);
  if (filters.province) params.set("province", filters.province);
  if (filters.search) params.set("search", filters.search);

  const resp = await fetchWithTimeout(`${API_BASE}/library?${params}`);
  if (!resp.ok) throw new Error("Failed to load library");
  return resp.json();
}

async function deleteLibraryFile(fileId) {
  const resp = await fetchWithTimeout(`${API_BASE}/library/${fileId}`, { method: "DELETE" });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(err.detail || "Delete failed");
  }
}

// --- Marketplace ---

async function browseMarketplace(page = 1, perPage = 20, filters = {}) {
  const params = new URLSearchParams({ page, per_page: perPage });
  if (filters.product_type) params.set("product_type", filters.product_type);
  if (filters.province) params.set("province", filters.province);
  if (filters.search) params.set("search", filters.search);
  if (filters.sort) params.set("sort", filters.sort);

  const resp = await fetchWithTimeout(`${API_BASE}/marketplace?${params}`);
  if (!resp.ok) throw new Error("Failed to load marketplace");
  return resp.json();
}

async function createListing(fileId, title, priceCents, description, tags) {
  const resp = await fetchWithTimeout(`${API_BASE}/marketplace/list`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      file_id: fileId,
      title,
      price_cents: priceCents,
      description,
      tags,
    }),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(err.detail || "Listing failed");
  }
  return resp.json();
}

async function purchaseListing(listingId) {
  const resp = await fetchWithTimeout(`${API_BASE}/marketplace/purchase`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ listing_id: listingId }),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(err.detail || "Purchase failed");
  }
  return resp.json();
}

async function getSellerDashboard() {
  const resp = await fetchWithTimeout(`${API_BASE}/marketplace/dashboard`);
  if (!resp.ok) throw new Error("Failed to load dashboard");
  return resp.json();
}

async function submitReview(listingId, rating, comment, cncCompatible) {
  const resp = await fetchWithTimeout(`${API_BASE}/marketplace/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      listing_id: listingId,
      rating,
      comment,
      cnc_compatible: cncCompatible,
    }),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(err.detail || "Review failed");
  }
  return resp.json();
}

async function getReviews(listingId) {
  const resp = await fetchWithTimeout(`${API_BASE}/marketplace/reviews/${listingId}`);
  if (!resp.ok) throw new Error("Failed to load reviews");
  return resp.json();
}

export {
  setToken, getToken, register, login, logout, getProfile,
  searchLocations, generateSVG, generatePin, batchGenerate,
  downloadSVG, downloadDXF, downloadThumbnail,
  getLibrary, deleteLibraryFile,
  browseMarketplace, createListing, purchaseListing,
  getSellerDashboard, submitReview, getReviews,
};
