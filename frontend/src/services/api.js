/**
 * MapForge — API client with auth support
 */

const API_BASE = "/api/v1";
const TIMEOUT_MS = 30000;
const ENV_API_ORIGIN = (import.meta.env.VITE_API_URL || "").trim().replace(/\/+$/, "");

let authToken = localStorage.getItem("mapforge_token") || null;

function buildApiFallbackOrigins() {
  const origins = [];
  if (ENV_API_ORIGIN) {
    origins.push(ENV_API_ORIGIN);
  }
  if (typeof window !== "undefined") {
    const host = window.location.hostname;
    const protocol = window.location.protocol || "http:";
    if (host === "localhost" || host === "127.0.0.1") {
      origins.push(`${protocol}//${host}:8000`);
    }
  }
  return [...new Set(origins)];
}

const API_FALLBACK_ORIGINS = buildApiFallbackOrigins();

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

function extractErrorMessage(detail, fallback) {
  if (!detail) return fallback;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => {
        const loc = d.loc ? d.loc.join(" > ") : "";
        const msg = d.msg || String(d);
        return loc ? `${loc}: ${msg}` : msg;
      })
      .join("; ");
  }
  return String(detail);
}

async function fetchWithTimeout(url, options = {}) {
  const timeoutMs = options.timeout || TIMEOUT_MS;
  const requestOptions = { ...options };
  delete requestOptions.timeout;

  const candidateUrls = [url];
  if (typeof url === "string" && url.startsWith("/api/")) {
    for (const origin of API_FALLBACK_ORIGINS) {
      const candidate = `${origin}${url}`;
      if (!candidateUrls.includes(candidate)) {
        candidateUrls.push(candidate);
      }
    }
  }

  let lastError = null;
  for (let i = 0; i < candidateUrls.length; i += 1) {
    const candidateUrl = candidateUrls[i];
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    const headers = { ...requestOptions.headers };
    if (authToken) {
      headers["Authorization"] = `Bearer ${authToken}`;
    }

    try {
      return await fetch(candidateUrl, { ...requestOptions, headers, signal: controller.signal });
    } catch (err) {
      if (err.name === "AbortError") {
        clearTimeout(timeout);
        throw new Error("Request timed out. Please check your connection and try again.");
      }
      lastError = err;
      const isFinalAttempt = i === candidateUrls.length - 1;
      if (isFinalAttempt) {
        const endpoint = typeof url === "string" ? String(url).split("?")[0] : "API request";
        const reason = err?.message ? ` (${err.message})` : "";
        const attempted = candidateUrls
          .map((u) => (typeof u === "string" ? String(u).split("?")[0] : "API request"))
          .join(", ");
        throw new Error(
          `Network error while calling ${endpoint}${reason}. Please check your connection and API server. Tried: ${attempted}`
        );
      }
    } finally {
      clearTimeout(timeout);
    }
  }

  const reason = lastError?.message ? ` (${lastError.message})` : "";
  throw new Error(`Network error while calling API request${reason}. Please check your connection and API server.`);
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
    throw new Error(extractErrorMessage(err.detail, "Registration failed"));
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
    throw new Error(extractErrorMessage(err.detail, "Login failed"));
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

async function requestPasswordReset(email) {
  let resp = await fetchWithTimeout(`${API_BASE}/auth/request-reset`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
  if (resp.status === 404 || resp.status === 405 || resp.status === 422) {
    // Backward compatibility for older backend deployments.
    resp = await fetchWithTimeout(`${API_BASE}/auth/request-reset?email=${encodeURIComponent(email)}`, {
      method: "POST",
    });
  }
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(extractErrorMessage(err.detail, "Reset request failed"));
  }
  return resp.json();
}

async function resetPassword(token, newPassword) {
  let resp = await fetchWithTimeout(`${API_BASE}/auth/reset-password`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token, new_password: newPassword }),
  });
  if (resp.status === 404 || resp.status === 405 || resp.status === 422) {
    // Backward compatibility for older backend deployments.
    resp = await fetchWithTimeout(
      `${API_BASE}/auth/reset-password?token=${encodeURIComponent(token)}&new_password=${encodeURIComponent(newPassword)}`,
      { method: "POST" }
    );
  }
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(extractErrorMessage(err.detail, "Reset failed"));
  }
  return resp.json();
}

async function subscribe(plan) {
  const resp = await fetchWithTimeout(`${API_BASE}/auth/subscribe`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      plan,
      success_url: window.location.origin + "?upgraded=1",
      cancel_url: window.location.origin,
    }),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(extractErrorMessage(err.detail, "Subscription failed"));
  }
  return resp.json();
}

// --- Search ---

async function searchLocations(query, country = "ca") {
  const resp = await fetchWithTimeout(
    `${API_BASE}/search?q=${encodeURIComponent(query)}&country=${encodeURIComponent(country)}&limit=10`
  );
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(extractErrorMessage(err.detail, "Search failed"));
  }
  return resp.json();
}

// --- Generate ---

async function generateSVG(params) {
  const resp = await fetchWithTimeout(`${API_BASE}/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
    timeout: 180000,
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(extractErrorMessage(err.detail, "Generation failed"));
  }
  return resp.json();
}

async function generatePin(params) {
  const resp = await fetchWithTimeout(`${API_BASE}/generate/pin`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
    timeout: 180000,
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(extractErrorMessage(err.detail, "Pin generation failed"));
  }
  return resp.json();
}

async function batchGenerate(items) {
  const resp = await fetchWithTimeout(`${API_BASE}/generate/batch`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items }),
    timeout: 300000,
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(extractErrorMessage(err.detail, "Batch generation failed"));
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

async function downloadSTL(fileId) {
  const resp = await fetchWithTimeout(`${API_BASE}/download/${fileId}?format=stl`);
  if (!resp.ok) throw new Error("STL download failed");
  return resp.blob();
}

async function downloadThumbnail(fileId) {
  const resp = await fetchWithTimeout(`${API_BASE}/download/${fileId}/thumbnail`);
  if (!resp.ok) throw new Error("Thumbnail download failed");
  return resp.blob();
}

async function downloadPrintPNG(fileId) {
  const resp = await fetchWithTimeout(`${API_BASE}/download/${fileId}?format=png`);
  if (!resp.ok) throw new Error("Print PNG download failed");
  return resp.blob();
}

async function downloadEtsyListing(fileId) {
  const resp = await fetchWithTimeout(`${API_BASE}/download/${fileId}/etsy`);
  if (!resp.ok) throw new Error("Etsy listing image download failed");
  return resp.blob();
}

async function downloadPreview(fileId) {
  const resp = await fetchWithTimeout(`${API_BASE}/download/${fileId}/preview`);
  if (!resp.ok) throw new Error("Preview download failed");
  return resp.blob();
}

async function downloadWallMockup(fileId, style = "light_wall") {
  const resp = await fetchWithTimeout(
    `${API_BASE}/download/${fileId}/wall-mockup?style=${encodeURIComponent(style)}`,
    { timeout: 45000 },
  );
  if (!resp.ok) throw new Error("Wall mockup download failed");
  return resp.blob();
}

async function downloadEtsyPackage(fileId) {
  const resp = await fetchWithTimeout(`${API_BASE}/download/${fileId}/etsy-package`, {
    timeout: 60000,
  });
  if (!resp.ok) throw new Error("Etsy package download failed");
  return resp.blob();
}

async function getPrintSizes() {
  const resp = await fetchWithTimeout(`${API_BASE}/print-sizes`);
  if (!resp.ok) throw new Error("Failed to load print sizes");
  return resp.json();
}

async function getPublicConfig() {
  const resp = await fetchWithTimeout(`${API_BASE}/config`);
  if (!resp.ok) return {};
  return resp.json();
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
    throw new Error(extractErrorMessage(err.detail, "Delete failed"));
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
    throw new Error(extractErrorMessage(err.detail, "Listing failed"));
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
    throw new Error(extractErrorMessage(err.detail, "Purchase failed"));
  }
  return resp.json();
}

async function getMyPurchases() {
  const resp = await fetchWithTimeout(`${API_BASE}/marketplace/purchases`);
  if (!resp.ok) throw new Error("Failed to load purchases");
  return resp.json();
}

async function updateListing(listingId, updates) {
  const resp = await fetchWithTimeout(`${API_BASE}/marketplace/${listingId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(extractErrorMessage(err.detail, "Update failed"));
  }
  return resp.json();
}

async function removeListing(listingId) {
  const resp = await fetchWithTimeout(`${API_BASE}/marketplace/${listingId}`, {
    method: "DELETE",
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(extractErrorMessage(err.detail, "Remove failed"));
  }
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
    throw new Error(extractErrorMessage(err.detail, "Review failed"));
  }
  return resp.json();
}

async function getReviews(listingId) {
  const resp = await fetchWithTimeout(`${API_BASE}/marketplace/reviews/${listingId}`);
  if (!resp.ok) throw new Error("Failed to load reviews");
  return resp.json();
}

async function aiDescribe(locationName, style, country = "", isCity = false, province = "") {
  const params = new URLSearchParams({
    location_name: locationName,
    style,
    country,
    is_city: isCity,
    province,
  });
  const resp = await fetchWithTimeout(`${API_BASE}/marketplace/ai-describe?${params}`, {
    method: "POST",
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(extractErrorMessage(err.detail, "AI description generation failed"));
  }
  return resp.json();
}

// --- Etsy Integration ---

async function getEtsyStatus() {
  const resp = await fetchWithTimeout(`${API_BASE}/etsy/status`, {
    headers: { Authorization: `Bearer ${authToken}` },
  });
  if (!resp.ok) return { connected: false };
  return resp.json();
}

async function connectEtsy() {
  const resp = await fetchWithTimeout(`${API_BASE}/etsy/connect`, {
    headers: { Authorization: `Bearer ${authToken}` },
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(extractErrorMessage(err.detail, "Failed to start Etsy connection"));
  }
  return resp.json();
}

async function disconnectEtsy() {
  const resp = await fetchWithTimeout(`${API_BASE}/etsy/disconnect`, {
    method: "POST",
    headers: { Authorization: `Bearer ${authToken}` },
  });
  if (!resp.ok) throw new Error("Failed to disconnect Etsy");
  return resp.json();
}

async function publishToEtsy(fileId, title, description, price, tags) {
  const resp = await fetchWithTimeout(`${API_BASE}/etsy/publish`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${authToken}`,
    },
    body: JSON.stringify({
      file_id: fileId,
      title,
      description,
      price: parseFloat(price),
      tags: typeof tags === "string" ? tags.split(",").map((t) => t.trim()).filter(Boolean) : tags,
    }),
    timeout: 60000,
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(extractErrorMessage(err.detail, "Failed to publish to Etsy"));
  }
  return resp.json();
}

async function getShowcaseCities() {
  const resp = await fetchWithTimeout(`${API_BASE}/etsy/showcase-cities`, {
    headers: { Authorization: `Bearer ${authToken}` },
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(extractErrorMessage(err.detail, "Failed to load showcase cities"));
  }
  return resp.json();
}

async function showcasePublish(city, options = {}) {
  const resp = await fetchWithTimeout(`${API_BASE}/etsy/showcase-publish`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${authToken}`,
    },
    body: JSON.stringify({
      city,
      color_theme: options.color_theme || "classic",
      poster_layout: options.poster_layout || "classic",
      font_family: options.font_family || "sans",
      board_size: options.board_size || "print_16x20",
      price: options.price || 9.99,
      title: options.title || null,
      description: options.description || null,
      tags: options.tags || null,
    }),
    timeout: 180000,
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(extractErrorMessage(err.detail, "Showcase publish failed"));
  }
  return resp.json();
}

async function getEtsyDebug() {
  const resp = await fetchWithTimeout(`${API_BASE}/admin/etsy-debug`, {
    headers: { Authorization: `Bearer ${authToken}` },
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(extractErrorMessage(err.detail, "Debug check failed"));
  }
  return resp.json();
}

async function getAdminStats() {
  const resp = await fetchWithTimeout(`${API_BASE}/admin/stats`, {
    headers: { Authorization: `Bearer ${authToken}` },
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(extractErrorMessage(err.detail, "Failed to load admin stats"));
  }
  return resp.json();
}

// --- Admin Etsy Settings ---

async function getEtsySettings() {
  const resp = await fetchWithTimeout(`${API_BASE}/admin/etsy-settings`);
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(extractErrorMessage(err.detail, "Failed to load Etsy settings"));
  }
  return resp.json();
}

async function saveEtsySettings(apiKey, apiSecret, redirectUri) {
  const resp = await fetchWithTimeout(`${API_BASE}/admin/etsy-settings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      api_key: apiKey,
      api_secret: apiSecret,
      redirect_uri: redirectUri,
    }),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(extractErrorMessage(err.detail, "Failed to save Etsy settings"));
  }
  return resp.json();
}

async function clearEtsySettings() {
  const resp = await fetchWithTimeout(`${API_BASE}/admin/etsy-settings`, {
    method: "DELETE",
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(extractErrorMessage(err.detail, "Failed to clear Etsy settings"));
  }
  return resp.json();
}

// --- Design Credits (Etsy-paid customers) ---

async function redeemCredit(token) {
  const resp = await fetchWithTimeout(`${API_BASE}/orders/redeem/${token}`);
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(extractErrorMessage(err.detail, "Invalid design credit"));
  }
  return resp.json();
}

async function generateForCredit(token, designConfig) {
  const resp = await fetchWithTimeout(`${API_BASE}/orders/generate/${token}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ design_config: designConfig }),
    timeout: 120000,
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(extractErrorMessage(err.detail, "Generation failed"));
  }
  return resp.json();
}

async function getCreditStatus(token) {
  const resp = await fetchWithTimeout(`${API_BASE}/orders/status/${token}`);
  if (!resp.ok) throw new Error("Credit not found");
  return resp.json();
}

async function downloadCreditFile(token, format = "png") {
  const resp = await fetchWithTimeout(`${API_BASE}/orders/download/${token}?format=${format}`, {
    timeout: 60000,
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(extractErrorMessage(err.detail, "Download failed"));
  }
  return resp.blob();
}

export {
  setToken, getToken, register, login, logout, getProfile, requestPasswordReset, resetPassword, subscribe,
  searchLocations, generateSVG, generatePin, batchGenerate,
  downloadSVG, downloadDXF, downloadSTL, downloadThumbnail, downloadPrintPNG,
  downloadEtsyListing, downloadEtsyPackage, downloadPreview, downloadWallMockup, getPrintSizes,
  getPublicConfig,
  getLibrary, deleteLibraryFile,
  browseMarketplace, createListing, purchaseListing,
  getMyPurchases, updateListing, removeListing,
  getSellerDashboard, submitReview, getReviews,
  aiDescribe,
  getEtsyStatus, connectEtsy, disconnectEtsy, publishToEtsy,
  getShowcaseCities, showcasePublish,
  getEtsyDebug, getAdminStats, getEtsySettings, saveEtsySettings, clearEtsySettings,
  redeemCredit, generateForCredit, getCreditStatus, downloadCreditFile,
};
