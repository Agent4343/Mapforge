# MapForge CNC — Product Story Bible

**Canadian Geographic SVG Generator for CNC Routing**

MapForge CNC is a cross-platform application that transforms any Canadian geographic location — lakes, provinces, cities, national parks, communities — into production-ready SVG files optimized for CNC routing with VCarve Pro and similar CAM software. Users search for a location, customize the design, and export a dimensionally accurate SVG file ready for immediate import and toolpath generation.

The application serves two revenue streams: (1) generating files for in-house CNC production of physical wood signs and maps, and (2) selling the SVG files as digital downloads on Etsy, Shopify, and the app's own marketplace.

| | |
|---|---|
| **Document** | Product Story Bible — Complete Technical & Business Specification |
| **Product** | MapForge CNC |
| **Version** | 1.0 |
| **Date** | March 15, 2026 |
| **Platform** | iOS (primary) • Web App (secondary) • Desktop (future) |
| **Tech Stack** | SwiftUI / React • Python Backend • OpenStreetMap APIs • QGIS Libraries |
| **Target CNC** | Onefinity Journeyman (48"×32") • VCarve Pro Compatible |
| **Author** | MapForge Product Team |

---

## Table of Contents

1. [Product Vision & Elevator Pitch](#1-product-vision--elevator-pitch)
2. [Problem Statement & Market Opportunity](#2-problem-statement--market-opportunity)
3. [Core User Personas](#3-core-user-personas)
4. [Product Architecture Overview](#4-product-architecture-overview)
5. [Geographic Data Pipeline (Technical Deep Dive)](#5-geographic-data-pipeline)
6. [SVG Generation Engine (CNC-Correct Output Spec)](#6-svg-generation-engine)
7. [VCarve Pro Compatibility & CNC Toolpath Mapping](#7-vcarve-pro-compatibility--cnc-toolpath-mapping)
8. [Product Types & Feature Matrix](#8-product-types--feature-matrix)
9. [User Interface & User Experience Flow](#9-user-interface--user-experience-flow)
10. [iOS App Architecture (SwiftUI)](#10-ios-app-architecture)
11. [Backend Architecture (Python / Railway)](#11-backend-architecture)
12. [Data Sources & Licensing](#12-data-sources--licensing)
13. [Business Model & Pricing Strategy](#13-business-model--pricing-strategy)
14. [Digital File Marketplace](#14-digital-file-marketplace)
15. [Etsy Integration Strategy](#15-etsy-integration-strategy)
16. [Development Roadmap](#16-development-roadmap)
17. [Marketing & Growth Strategy](#17-marketing--growth-strategy)
18. [Technical Specifications & SVG Output Reference](#18-technical-specifications--svg-output-reference)
19. [Competitive Analysis](#19-competitive-analysis)
20. [Appendix: SVG Code Examples](#20-appendix-svg-code-examples)

---

## 1. Product Vision & Elevator Pitch

### The One-Liner

**MapForge CNC turns any Canadian location into a CNC-ready SVG file in under 60 seconds.**

### The Elevator Pitch

Canada has over 2 million named lakes, 13 provinces and territories, thousands of communities, and 48 national parks. Every one of them is a potential product — a carved wooden map that somebody will pay $60–$400 for. The bottleneck has always been the design step: sourcing geographic data, cleaning it up in GIS software, and converting it to CNC-compatible vector files. That process takes 30–90 minutes per location for an experienced user.

MapForge CNC eliminates that bottleneck entirely. A user types in a lake name, province, city, or national park, and the app pulls real geographic boundary data from open Canadian sources, processes it into clean vector paths, lets them customize text and sizing, and exports a production-ready SVG file that imports directly into VCarve Pro with zero additional cleanup.

The app serves two markets simultaneously: CNC operators who cut physical products (signs, maps, wall art) and digital file buyers who purchase SVG/DXF files for their own CNC machines or laser cutters. This creates a dual-revenue flywheel — every location processed becomes both a potential physical product and a digital download.

### Core Value Propositions

- **For CNC Operators:** Eliminate the QGIS/design bottleneck. Go from customer order to CNC file in under 60 seconds instead of 30–90 minutes. Handle custom lake orders without GIS expertise.
- **For Digital File Buyers:** Purchase verified, CNC-tested SVG files of any Canadian lake, province, or city. No design skills needed — buy, download, import, cut.
- **For the Business:** Every file generated builds a template library. Popular locations become instant-delivery digital products. The library compounds over time.

### Vision Statement

> MapForge CNC will become the definitive tool for generating CNC-ready geographic art files for Canada, expanding to the US and globally. Our template library will grow to 10,000+ pre-generated locations within 18 months, creating the largest CNC-ready geographic file marketplace in North America.

---

## 2. Problem Statement & Market Opportunity

### The Problem

The market for custom carved geographic art (lake maps, province silhouettes, city maps, topographic pieces) is large and growing. CNC routers and laser cutters have become affordable enough for small operators and hobbyists. However, there is a critical gap between having a CNC machine and being able to efficiently produce geographic products:

- **GIS expertise required:** Sourcing accurate geographic data requires knowledge of QGIS, Shapefiles, GeoJSON, and government data portals (NRCAN, OpenStreetMap, Canadian Hydrographic Service). Most CNC operators do not have this background.
- **Conversion is manual and slow:** Even for skilled users, the pipeline from raw geographic data to a clean SVG suitable for CNC routing takes 30–90 minutes per location. This includes downloading data, cropping, cleaning geometry, simplifying paths, adding text, and exporting.
- **Quality is inconsistent:** Manual conversion produces SVGs with varying quality — unclosed paths, excessive node counts (which choke CNC controllers), incorrect scale, and paths that don't map cleanly to CNC toolpaths.
- **No centralized file marketplace:** There is no single marketplace where CNC operators can buy verified, CNC-ready geographic SVG files. Etsy has some, but quality varies wildly and coverage is spotty.

### Market Size

| Segment | Size | Notes |
|---|---|---|
| CNC machine owners (Canada) | ~50,000–80,000 | Hobbyist + small business, growing 15–20%/year |
| CNC machine owners (US) | ~400,000–600,000 | Future expansion market |
| Laser cutter owners (Canada + US) | ~200,000+ | Also consume SVG files; secondary market |
| Etsy "custom lake map" searches/month | ~8,000–12,000 | High buyer intent; growing category |
| Canadian cottage/cabin owners | ~1,800,000 | Primary physical product buyers |
| Total addressable digital file market | $5M–$15M/year | Based on avg. $8 file price × estimated demand |

---

## 3. Core User Personas

### Persona 1: The CNC Side-Hustler

**Name:** Mike, 38 • **Location:** Barrie, Ontario • **Machine:** Onefinity Woodworker

Mike bought a CNC router during COVID and makes personalized signs on weekends. He's seen lake maps selling for $150–$300 on Etsy but doesn't know how to source the geographic data. He's tried tracing Google Maps screenshots in Inkscape but the results are rough and take hours. He would pay for an app that gives him a clean SVG file of any lake his customers request.

- **Pain point:** Can't efficiently create custom lake/topo map files
- **Willingness to pay:** $15–$30/month for unlimited SVG generation, or $5–$15 per file
- **Success metric:** Go from customer order to CNC file in under 5 minutes

### Persona 2: The Etsy Seller

**Name:** Sarah, 44 • **Location:** Kelowna, BC • **Machine:** Shapeoko 4 XL

Sarah runs an established Etsy shop selling custom wood signs. She gets frequent requests for lake maps (especially Okanagan, Shuswap, Kalamalka) but turns them down because the design process is too slow to be profitable. She wants a tool that lets her accept every custom lake order instantly.

- **Pain point:** Losing revenue by turning down custom geographic orders
- **Willingness to pay:** $25–$50/month for a tool that adds $500+/month in new revenue
- **Success metric:** Accept and fulfill 10+ custom lake orders per month

### Persona 3: The Digital File Buyer

**Name:** Tom, 52 • **Location:** Muskoka, Ontario • **Machine:** X-Carve Pro

Tom is a hobbyist who makes projects for family and friends. He wants a CNC file of his cottage lake as a retirement gift for his father. He doesn't want a subscription — he wants to buy one file, download it, and cut it. He'll pay $10–$20 for a file that saves him hours of work.

- **Pain point:** Needs a specific file, doesn't want to learn GIS software
- **Willingness to pay:** $8–$20 per file (one-time)
- **Success metric:** Download a working SVG and have it cutting within 30 minutes

### Persona 4: The Owner-Operator (You)

**Profile:** Onefinity Journeyman owner, VCarve Pro user, producing physical products for Etsy and local markets. Uses MapForge as both a production tool (generating files to cut in-house) and a revenue generator (selling digital files). The app eliminates the design bottleneck and opens the door to accepting any Canadian location as a custom order.

---

## 4. Product Architecture Overview

### System Architecture Diagram

MapForge CNC is a three-tier system: a client application (iOS + web), a processing backend (Python on Railway), and external geographic data sources.

| Layer | Technology | Responsibility |
|---|---|---|
| Client (iOS) | SwiftUI, MapKit, CoreGraphics | Search UI, map preview, SVG customization, export, in-app purchase |
| Client (Web) | React, SVG.js, Leaflet | Browser-based search, preview, export. Marketplace storefront. |
| API Layer | Python FastAPI on Railway | Geo data fetching, geometry processing, SVG generation, user auth, file storage |
| Geo Processing | Shapely, GeoPandas, pyproj, svgwrite | Polygon simplification, projection, SVG path generation, CNC optimization |
| Data Sources | OSM Nominatim, Overpass API, NRCAN CanVec | Geographic boundary data for all Canadian locations |
| Storage | Supabase (PostgreSQL + S3) | User accounts, generated SVG library, order history, digital marketplace |
| Payments | StoreKit 2 (iOS), Stripe (Web) | Subscriptions, per-file purchases, marketplace transactions |

### Data Flow

The end-to-end data flow for generating a CNC-ready SVG:

1. **Search:** User enters location name → Client sends query to Nominatim API → Returns lat/lng + OSM ID + basic polygon (if available)
2. **Fetch Geometry:** Client/backend fetches full geometry from Overpass API using OSM ID → Returns GeoJSON polygon(s) with full shoreline/boundary coordinates
3. **Process Geometry:** Backend processes raw GeoJSON: reproject to Mercator, simplify paths (Douglas-Peucker algorithm), remove micro-islands below threshold, close all paths, validate winding order
4. **Generate SVG:** Backend converts processed geometry to SVG paths scaled to user-selected board dimensions (in mm). Adds text elements, coordinate labels, board outline, CNC metadata comments.
5. **Preview:** Client renders SVG preview with simulated wood background. User adjusts text, font size, coordinates toggle, board size, cut style.
6. **Export:** User downloads final SVG. File is dimensioned in mm, all paths closed, optimized node count, ready for VCarve Pro import.
7. **Library Cache:** Generated SVG is cached in Supabase. Future requests for the same location are instant (no re-processing). File is optionally added to the digital marketplace.

---

## 5. Geographic Data Pipeline

### Data Sources

| Source | Data Type | Coverage | License | Use Case |
|---|---|---|---|---|
| OpenStreetMap Nominatim | Geocoding + basic polygons | Global | ODbL (free, attribution) | Location search, initial geometry |
| Overpass API | Full geometry (GeoJSON) | Global | ODbL (free, attribution) | Detailed shorelines, boundaries, streets |
| NRCAN CanVec | Topographic vectors | Canada | Open Government License | High-quality Canadian topo data |
| Canadian Hydrographic Service | Bathymetric depth | Canadian waters | Open Government License | 3D lake depth contours |
| Natural Earth | Province/country outlines | Global | Public domain | Clean province silhouettes |
| StatsCan Boundary Files | Census boundaries | Canada | Open Government License | City boundaries, municipal limits |

### Geocoding Pipeline

When a user searches for a location, the system queries in this priority order:

1. **Priority 1 — Local Cache:** Check Supabase for a previously generated file for this location. If found, return cached SVG instantly (< 200ms response).
2. **Priority 2 — Nominatim + Polygon:** Query Nominatim with `polygon_geojson=1`. Many features (provinces, large lakes, cities) return full geometry inline. This is the fastest path for new locations.
3. **Priority 3 — Overpass API:** If Nominatim doesn't return sufficient geometry, use the OSM ID to query Overpass for full way/relation geometry. This handles complex features with multiple rings (island lakes, archipelagos, detailed coastlines).
4. **Priority 4 — NRCAN CanVec:** For high-fidelity Canadian topo data (contour lines, detailed hydrography), pull from pre-downloaded CanVec shapefiles stored on the backend. This is used for the premium topo/bathymetric products.

### Geometry Processing Pipeline

Raw geographic data must be processed before SVG generation. The pipeline uses Shapely (Python geometry library) and runs on the Railway backend:

| Step | Operation | Why It Matters for CNC |
|---|---|---|
| 1. Parse | Parse GeoJSON into Shapely Polygon/MultiPolygon objects | Validates geometry integrity |
| 2. Reproject | Convert from WGS84 (lat/lng) to Web Mercator (meters) using pyproj | Preserves shape proportions for carving |
| 3. Simplify | Douglas-Peucker simplification with configurable tolerance | Reduces node count for smooth CNC motion. Too many nodes = stuttering. |
| 4. Filter | Remove polygons below minimum area threshold | Eliminates micro-islands that are too small to carve |
| 5. Close Paths | Ensure all polygon rings are closed (first point = last point) | **CRITICAL:** Open paths cause VCarve profile cut failures |
| 6. Winding Order | Enforce counter-clockwise exterior, clockwise holes | Correct winding = correct inside/outside detection in CAM |
| 7. Scale | Scale to target board dimensions (mm) | SVG dimensions must match physical board size exactly |
| 8. Optimize | Remove collinear points, merge near-coincident vertices | Cleaner toolpaths, faster CNC execution, smoother curves |

> **CRITICAL CNC REQUIREMENT:** Every exported SVG path MUST be a closed polygon. Open paths will cause VCarve Pro to generate incomplete profile toolpaths, resulting in the bit not returning to the start point. The geometry processing pipeline validates this as the final step and throws an error if any path is unclosed.

---

## 6. SVG Generation Engine

The SVG generation engine is the core of MapForge CNC. It converts processed geometry into SVG files that meet strict CNC compatibility requirements.

### SVG Output Specification

| Parameter | Value | Rationale |
|---|---|---|
| Units | Millimeters (mm) | VCarve Pro imports mm natively. Avoids scaling errors. |
| Coordinate System | Top-left origin (SVG standard) | Matches VCarve Pro import behavior |
| ViewBox | `0 0 [width_mm] [height_mm]` | Ensures 1:1 scale on import |
| Width/Height | `[value]mm` (explicit mm unit) | Forces mm interpretation in CAM software |
| Stroke Width | 0.5mm for profile paths | Thin enough to not affect toolpath center |
| Fill | `none` (outline) or `#color` (pocket) | VCarve uses fill to determine pocket vs. profile |
| Path Format | M/L/Z commands only (no curves) | Straight line segments = predictable CNC motion |
| Max Node Count | < 5,000 per path | Prevents CNC controller buffer overflow |
| Path Closure | All paths end with Z command | Required for closed profile cuts |
| Decimal Precision | 2 decimal places (0.01mm) | More than sufficient for CNC accuracy |
| Text Elements | SVG `<text>` with system fonts | VCarve converts text to V-carve paths on import |
| Board Outline | Dashed rect at full dimensions | Visual reference; can be used as profile cut boundary |

### SVG Layer Structure

Each SVG file contains organized layers that map directly to CNC toolpaths:

| Layer Name | SVG Element | CNC Toolpath | Recommended Bit |
|---|---|---|---|
| `board_outline` | dashed stroke | Profile cut (optional) | 1/4" downcut endmill |
| `geography_outline` | closed, no fill | Profile cut with tabs | 1/4" downcut endmill |
| `geography_fill` | closed, with fill | Pocket toolpath | 1/4" upcut endmill |
| `contour_lines` | open strokes | V-carve or engrave | 60° or 90° V-bit |
| `text_primary` | location name | V-carve toolpath | 60° V-bit |
| `text_coordinates` | GPS coords | V-carve toolpath | 60° V-bit |
| `detail_lines` | roads/rivers | Engrave or V-carve | 1/8" ball nose or V-bit |
| `depth_bands` | closed, graded fill | Stepped pocket (multi-depth) | 1/8" ball nose endmill |

### Simplification Algorithm

The Douglas-Peucker simplification tolerance is critical for CNC output. Too aggressive = loss of geographic detail. Too conservative = too many nodes causing CNC stutter.

| Product Type | Tolerance (meters) | Typical Node Count | Result |
|---|---|---|---|
| Province silhouette | 500–1000m | 200–800 | Clean outline, smooth curves |
| Lake shoreline (small) | 20–50m | 300–1,500 | Recognizable shape with bays/inlets |
| Lake shoreline (large) | 50–200m | 500–3,000 | Balanced detail for large lakes |
| City boundary | 50–100m | 200–600 | Clean municipal outline |
| City street map | 5–20m | 2,000–5,000 | Recognizable street grid |
| Topo contour lines | 10–50m | 500–3,000 | Smooth elevation bands |
| Bathymetric depth | 10–30m | 500–2,000 | Clear depth contours |

> **ADAPTIVE SIMPLIFICATION:** The engine automatically adjusts tolerance based on the source feature's size. A small pond gets a finer tolerance than a large province outline. This ensures consistent visual quality across all product sizes.

---

## 7. VCarve Pro Compatibility & CNC Toolpath Mapping

### VCarve Pro Import Behavior

Understanding how VCarve Pro interprets SVG files is essential for generating correct output:

- **Units:** VCarve reads the width/height attributes. If they include "mm" (e.g., `width="406.4mm"`), it imports in millimeters. If unitless, it assumes the document's default unit. MapForge always exports with explicit mm units.
- **Paths:** SVG `<path>` elements become VCarve vector objects. Closed paths (ending with `Z`) become closed vectors that support profile and pocket toolpaths. Open paths become open vectors that only support engrave/V-carve toolpaths.
- **Fill:** VCarve ignores SVG fill colors but does distinguish between filled and unfilled paths. Filled paths are suitable for pocket operations. MapForge uses fill as a visual indicator and documents the intended toolpath in SVG comments.
- **Text:** SVG `<text>` elements are converted to VCarve text objects which can then be assigned V-carve toolpaths. The font must be available on the user's system. MapForge uses common system fonts (Arial, Helvetica) for maximum compatibility.
- **Groups:** SVG `<g>` elements are preserved as VCarve groups, which map to the layer structure described in Chapter 6. Users can select by group to quickly assign toolpaths to all geography paths, all text, etc.
- **Transforms:** VCarve handles SVG transforms (translate, scale, rotate) but complex nested transforms can cause positioning errors. MapForge pre-applies all transforms and exports flat coordinates to avoid this issue.

### Recommended Toolpath Assignment

MapForge SVG files include XML comments documenting the recommended VCarve toolpath for each layer:

| SVG Layer | VCarve Toolpath | Bit | Depth | Settings |
|---|---|---|---|---|
| `geography_outline` | Profile (outside) | 1/4" downcut | Through + 0.02" | Tabs: 3–5, 0.25" wide, 0.1" tall |
| `geography_fill` | Pocket | 1/4" upcut | 0.05"–0.1" | Raster angle: 0°, stepover: 40% |
| `contour_lines` | V-Carve | 60° V-bit | Auto (V-carve) | Flat depth: 0.1" |
| `text_primary` | V-Carve | 60° V-bit | Auto (V-carve) | Flat depth: 0.05" |
| `text_coordinates` | V-Carve | 60° V-bit | Auto (V-carve) | Flat depth: 0.03" |
| `depth_bands` | Pocket (stepped) | 1/8" ball nose | Variable | Each band = different depth level |
| `detail_lines` | Engrave | 1/8" ball nose | 0.03"–0.05" | Follow vector path |
| `board_outline` | Profile (inside) | 1/4" downcut | Through + 0.02" | Optional: only if cutting board to size |

### CNC Controller Compatibility

| Controller | Machine | SVG Support | Notes |
|---|---|---|---|
| Onefinity Controller | Onefinity Journeyman/Woodworker | Via VCarve/Carbide | Primary target. Buildbotics-based controller. |
| Carbide Motion | Shapeoko, Nomad | Via Carbide Create | Import SVG into Carbide Create for toolpaths |
| GRBL (generic) | X-Carve, OpenBuilds, etc. | Via any CAM software | SVG → CAM → G-code → GRBL |
| Mach3/Mach4 | Various CNC routers | Via VCarve/Fusion 360 | Professional-grade controller |
| LightBurn | Laser cutters | Direct SVG import | Secondary market — laser engraving |

---

## 8. Product Types & Feature Matrix

| Feature | Lake Map | Province | City | Park | Name Sign |
|---|---|---|---|---|---|
| Shoreline/boundary outline | ✓ | ✓ | ✓ | ✓ | — |
| Custom text overlay | ✓ | ✓ | ✓ | ✓ | ✓ |
| GPS coordinates | ✓ | ✓ | ✓ | ✓ | Optional |
| Depth contours (bathymetric) | Premium | — | — | — | — |
| Elevation contours (topo) | — | — | — | Premium | — |
| Street network | — | — | ✓ | — | — |
| Islands/interior features | ✓ | ✓ | — | ✓ | — |
| Multi-ring support | ✓ | ✓ | — | ✓ | — |
| Board size selection | ✓ | ✓ | ✓ | ✓ | ✓ |
| Cut style (outline/fill/engrave) | ✓ | ✓ | ✓ | ✓ | ✓ |
| VCarve toolpath comments | ✓ | ✓ | ✓ | ✓ | ✓ |
| DXF export | v1.1 | v1.1 | v1.1 | v1.1 | v1.1 |
| STL export (3D) | v2.0 | — | — | v2.0 | — |

✓ = Available at launch • Premium = Requires Pro subscription • v1.1/v2.0 = Planned for future version

---

## 9. User Interface & User Experience Flow

### Design Language

MapForge CNC uses a dark industrial aesthetic inspired by machining interfaces and topographic maps. The palette is charcoal (`#1a1a1a`) with crimson (`#c0392b`) accents, monospace typography (JetBrains Mono for data, Space Grotesk for headings), and a simulated wood-grain preview area.

- **Dark background:** Reduces eye strain during long production sessions. Matches workshop environments where screens are viewed in mixed lighting.
- **Crimson accents:** High contrast against dark backgrounds. Evokes precision tooling and CNC interfaces.
- **Monospace data:** Coordinates, dimensions, and technical parameters displayed in monospace for clarity and alignment.
- **Wood-grain preview:** SVG preview renders on a simulated wood background, giving users a realistic sense of how the carved piece will look.

### Screen Flow (iOS App)

#### Screen: Home / Dashboard
Product type selector (lake, province, city, park, name sign). Recent projects grid. Quick-access to template library. Subscription status.

#### Screen: Search
Search bar with auto-suggest. Results list showing location name, type, coordinates. Map preview (MapKit) showing selected area. Tap result to proceed.

#### Screen: Preview & Customize
Full-screen SVG preview on wood background. Left panel (or bottom sheet on mobile): text input, coordinate toggle, font size slider, board size selector, cut style picker. Real-time preview updates on every change.

#### Screen: Export
Export format selector (SVG primary, DXF future). File details summary (dimensions, node count, layer count). VCarve import instructions. Download button. Option to save to template library. Option to list on marketplace.

#### Screen: Template Library
Grid of previously generated files. Search/filter by province, type, popularity. Tap to preview, re-customize, or re-export. Indicates which files are listed on marketplace.

#### Screen: Marketplace
Browse/search all publicly listed files. Preview before purchase. One-tap buy with StoreKit 2. Instant download after purchase. Seller dashboard showing your listings, views, sales, revenue.

#### Screen: Settings
Account management. Subscription management. Default board size. Default export format. CNC machine profile (for optimized simplification). Connected Etsy shop (future integration).

---

## 10. iOS App Architecture

### Technology Stack

| Component | Technology | Purpose |
|---|---|---|
| UI Framework | SwiftUI | Native iOS interface with declarative syntax |
| Map Display | MapKit | Location search preview and satellite imagery |
| SVG Rendering | CoreGraphics + custom SVG parser | Real-time SVG preview on wood background |
| Networking | URLSession + async/await | API calls to backend and OSM services |
| Payments | StoreKit 2 | Subscriptions and per-file purchases |
| Local Storage | SwiftData | Cached files, recent projects, preferences |
| File Export | UIActivityViewController + Files.app | Save SVG to Files, AirDrop, share |
| Auth | Sign in with Apple + Supabase Auth | User accounts for marketplace and sync |

### Key Swift Components

- **MapForgeApp.swift:** App entry point, environment objects, StoreKit 2 subscription manager
- **GeoSearchService.swift:** Handles Nominatim + Overpass API calls, result parsing, caching
- **GeometryProcessor.swift:** Port of Python pipeline to Swift — Mercator projection, simplification, path closing, scaling
- **SVGGenerator.swift:** Generates SVG XML string from processed geometry + user customization options
- **SVGPreviewView.swift:** Custom SwiftUI view that renders SVG on wood-grain background using CoreGraphics
- **ExportManager.swift:** Handles SVG file creation, sharing, saving to Files app
- **TemplateLibraryView.swift:** Grid display of cached/generated files with search and filter
- **MarketplaceView.swift:** Browse, purchase, and manage digital file listings
- **SubscriptionManager.swift:** StoreKit 2 subscription lifecycle, entitlement checks

### Offline Capability

The iOS app can function partially offline by caching previously generated files in SwiftData. Users can re-export any cached file without network access. New searches require network connectivity for OSM/Nominatim API calls. Province silhouette templates are bundled in the app binary for instant offline access.

---

## 11. Backend Architecture

### Technology Stack

| Component | Technology | Purpose |
|---|---|---|
| Runtime | Python 3.12 | Geo processing ecosystem (Shapely, GeoPandas) |
| Framework | FastAPI | Async REST API with automatic OpenAPI docs |
| Hosting | Railway | Docker-based deployment, auto-scaling, GitHub CI/CD |
| Geo Processing | Shapely, GeoPandas, pyproj, Fiona | Geometry operations, coordinate projection, shapefile I/O |
| SVG Generation | svgwrite + custom engine | CNC-optimized SVG output |
| Database | Supabase (PostgreSQL) | User accounts, file library, marketplace, analytics |
| File Storage | Supabase Storage (S3) | SVG file hosting, thumbnails |
| Caching | Redis (Railway addon) | Geo query cache, rate limiting |
| Payments (web) | Stripe | Web marketplace transactions |

### API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/search?q={query}&type={type}` | Search Canadian locations via Nominatim |
| POST | `/api/v1/generate` | Generate SVG from location ID + customization params |
| GET | `/api/v1/preview/{file_id}` | Get SVG preview (thumbnail) |
| GET | `/api/v1/download/{file_id}` | Download full SVG file (auth required) |
| GET | `/api/v1/library` | List user's generated file library |
| GET | `/api/v1/marketplace` | Browse marketplace listings |
| POST | `/api/v1/marketplace/list` | List a file on the marketplace |
| POST | `/api/v1/marketplace/purchase` | Purchase a marketplace file |
| POST | `/api/v1/auth/register` | Create account |
| POST | `/api/v1/auth/login` | Login, returns JWT |

### Generate Endpoint Detail

The `/api/v1/generate` endpoint is the core of the backend. It accepts:

```json
{
  "osm_id": 12345678,
  "osm_type": "relation",
  "product_type": "lake",
  "board_width_inches": 16,
  "board_height_inches": 20,
  "style": "outline",
  "text": "Lake Muskoka",
  "show_coordinates": true,
  "font_size_mm": 12,
  "simplification": "auto",
  "include_islands": true,
  "min_island_area_m2": 5000
}
```

Returns: SVG file content (`Content-Type: image/svg+xml`) with CNC metadata headers.

---

## 12. Data Sources & Licensing

| Source | License | Requirements | Commercial Use |
|---|---|---|---|
| OpenStreetMap / Nominatim | Open Database License (ODbL) | Attribution required: "© OpenStreetMap contributors" | ✓ Yes, with attribution |
| Overpass API | ODbL (same as OSM) | Same attribution. Rate limit: 2 requests/sec | ✓ Yes |
| NRCAN CanVec / GeoGratis | Open Government Licence – Canada | Attribution to Government of Canada | ✓ Yes |
| Canadian Hydrographic Service | Open Government Licence | Attribution to CHS | ✓ Yes |
| Natural Earth | Public Domain | None required | ✓ Yes |
| StatsCan Boundary Files | Statistics Canada Open Licence | Attribution to Statistics Canada | ✓ Yes |

> **ALL data sources used by MapForge CNC are open-licensed for commercial use.** Generated SVG files can be freely sold as physical products or digital downloads. Attribution is included in the SVG file comments and on the app's about page.

### Attribution Implementation

Every generated SVG includes the following XML comment at the top of the file:

```xml
<!-- MapForge CNC - Generated SVG -->
<!-- Geographic data: © OpenStreetMap contributors (ODbL) -->
<!-- Canadian topo data: Natural Resources Canada, Open Government Licence -->
<!-- Generated: 2026-03-14T12:00:00Z -->
```

---

## 13. Business Model & Pricing Strategy

### Revenue Streams

MapForge CNC generates revenue from four sources:

| Stream | Model | Price | Target |
|---|---|---|---|
| 1. iOS App Subscription | Monthly/annual subscription via StoreKit 2 | $9.99/mo or $79.99/yr | CNC operators generating multiple files/month |
| 2. Per-File Purchase | One-time IAP per generated SVG | $4.99–$14.99/file | Casual users, hobbyists, one-off projects |
| 3. Digital Marketplace | Commission on file sales (20% platform fee) | $5.99–$19.99/file | File buyers who want ready-made SVGs |
| 4. Physical Product Sales | Your own Etsy/Shopify shop (100% margin to you) | $60–$400/piece | End consumers buying carved wood pieces |

### Subscription Tiers

| Feature | Free | Maker ($9.99/mo) | Pro ($24.99/mo) |
|---|---|---|---|
| Province silhouette SVGs | 3 free | Unlimited | Unlimited |
| Lake/city/park SVGs | — | 20/month | Unlimited |
| Bathymetric/topo layers | — | — | ✓ |
| DXF export | — | ✓ | ✓ |
| Template library | 5 files | 100 files | Unlimited |
| Marketplace selling | — | ✓ (25% fee) | ✓ (15% fee) |
| Batch generation | — | — | ✓ (up to 50) |
| API access | — | — | ✓ |
| Priority support | — | — | ✓ |
| Custom branding on SVGs | — | — | ✓ |

### Revenue Projections

| Metric | Month 3 | Month 6 | Month 12 | Month 24 |
|---|---|---|---|---|
| App downloads | 200 | 800 | 3,000 | 10,000 |
| Paid subscribers | 15 | 60 | 250 | 800 |
| Subscription MRR | $150 | $600 | $2,500 | $8,000 |
| Per-file purchases/mo | 20 | 80 | 300 | 1,000 |
| Per-file revenue/mo | $160 | $640 | $2,400 | $8,000 |
| Marketplace sales/mo | — | 30 | 150 | 500 |
| Marketplace commission/mo | — | $60 | $375 | $1,250 |
| Physical product sales/mo | $500 | $2,000 | $5,000 | $8,000 |
| **Total Monthly Revenue** | **$810** | **$3,300** | **$10,275** | **$25,250** |
| **Annualized Revenue** | **$9,720** | **$39,600** | **$123,300** | **$303,000** |

---

## 14. Digital File Marketplace

The MapForge Marketplace is an in-app store where users can buy and sell CNC-ready geographic SVG files. It creates a network effect: every file generated by any user potentially becomes a product that other users can purchase instantly.

### How It Works

- **Listing:** Any Pro or Maker subscriber can list generated SVGs on the marketplace. They set a price ($5.99–$19.99 recommended range). The file is verified for CNC compatibility before listing.
- **Discovery:** Buyers search by location name, province, product type, or browse curated collections ("Top Ontario Lakes", "Atlantic Canada", "National Parks").
- **Purchase:** One-tap purchase via StoreKit 2 (iOS) or Stripe (web). Instant download. No waiting for custom generation.
- **Revenue Split:** Seller receives 75–85% (depending on tier). MapForge retains 15–25% platform fee. Apple takes 15–30% on iOS IAP transactions.
- **Ratings & Reviews:** Buyers rate files on CNC compatibility, accuracy, and quality. High-rated files surface in search. Poor files are delisted.

### Marketplace Growth Strategy

Seed the marketplace with 100–200 files covering the most popular Canadian locations: top 50 cottage lakes (Muskoka, Kawarthas, Okanagan, Shuswap, etc.), all 13 province/territory silhouettes, top 25 Canadian cities, all 48 national parks (partial coverage), and 50+ quirky community name signs.

This initial seed library is generated using MapForge itself and listed at competitive prices ($7.99–$14.99). As subscribers generate files, the library grows organically. Target: 1,000 files by Month 6, 5,000 by Month 12, 10,000 by Month 18.

---

## 15. Etsy Integration Strategy

MapForge CNC complements an Etsy shop in two ways: generating SVGs for physical products you sell on Etsy, and selling the digital SVG files directly on Etsy as digital downloads.

### Physical Product Etsy Listings

Use MapForge to generate SVGs for every custom order. Your Etsy listings offer personalization (customer provides lake name, town, etc.). When an order comes in, you search the location in MapForge, generate the SVG, import into VCarve Pro, and cut. Turnaround: under 5 minutes from order to CNC file, versus 30–90 minutes manually.

### Digital File Etsy Listings

Create Etsy digital download listings for popular SVG files. Each file is listed at $8.99–$14.99 as an instant download. The description includes the SVG preview image, board dimensions, recommended bits, and VCarve import instructions. These listings have zero marginal cost (no materials, no shipping, no production time) and generate passive income.

### Etsy SEO Keywords

- "CNC lake map SVG", "lake map SVG file", "CNC file [lake name]"
- "province silhouette SVG", "Canada map CNC file"
- "custom lake map digital download", "CNC router file"
- "VCarve lake map", "laser cut lake map file"
- "[Province name] lake SVG", "[Lake name] CNC file"

---

## 16. Development Roadmap

| Phase | Timeline | Deliverables |
|---|---|---|
| v0.1 — MVP | Weeks 1–4 | React web app with search, preview, SVG export. Lake maps + province silhouettes. Nominatim + Overpass integration. |
| v0.2 — Backend | Weeks 5–8 | Python FastAPI backend on Railway. Shapely geometry processing. Supabase integration. User accounts. |
| v0.3 — iOS App | Weeks 9–14 | SwiftUI iOS app. MapKit search. CoreGraphics preview. File export to Files app. StoreKit 2 subscriptions. |
| v1.0 — Launch | Weeks 15–18 | App Store submission. All 5 product types. Template library. Per-file purchase. Seed marketplace with 100+ files. |
| v1.1 — DXF | Weeks 19–22 | DXF export format. City street maps (OSM road network). Improved simplification algorithm. Batch generation for Pro users. |
| v1.2 — Marketplace | Weeks 23–28 | Full marketplace with seller dashboard. Ratings/reviews. Curated collections. Stripe web payments. |
| v2.0 — 3D & US | Months 8–12 | Bathymetric 3D lake maps (STL export). Topo elevation maps. US expansion (USGS data). Etsy API integration for auto-listing. |
| v3.0 — Global | Year 2 | Global coverage (Europe, Australia, etc.). Partnership with CNC manufacturers. White-label API for other CNC software. |

### Key Milestones

- First working SVG imported into VCarve Pro successfully
- Server-side SVG generation. File caching operational.
- TestFlight beta. First subscriber.
- App Store approval. Public launch.
- 100 paid subscribers
- 500 marketplace files. First third-party sale.
- $10K MRR. 1,000 subscribers.
- $25K MRR. 10,000+ marketplace files.

---

## 17. Marketing & Growth Strategy

### Channel Strategy

- **YouTube (Primary):** "How I make $X/month selling CNC lake maps" style content. Tutorial videos showing MapForge workflow. CNC process videos (satisfying carving content). This is the #1 channel for reaching CNC operators.
- **TikTok / Instagram Reels:** Short-form CNC carving videos. Before/after reveals (SVG file → finished wood piece). Satisfying woodworking content drives organic reach.
- **CNC Forums & Communities:** Onefinity Forum, CNCZone, r/CNC, r/hobbycnc, Facebook CNC groups. Provide genuine value (free tips, workflow advice) and mention MapForge organically.
- **Etsy SEO:** Both physical products and digital files rank in Etsy search. Each listing is a marketing channel that compounds over time.
- **App Store Optimization:** Keywords: "CNC", "lake map", "SVG generator", "wood map", "topographic". Screenshots showing the search → preview → export flow.
- **Partnerships:** Approach Onefinity, Vectric (VCarve), Carbide 3D for potential partnership/promotion. Offer affiliate commissions to CNC YouTubers.

### Content Calendar (First 90 Days)

- **Week 1:** Launch video: "I Built an App That Turns Any Canadian Lake Into a CNC File"
- **Week 2–4:** Weekly tutorial: one lake map build from search to finished piece (different lake each week)
- **Week 5–8:** "Top 10 Cottage Lakes for CNC Maps" listicle video. Province silhouette showcase. Customer reaction videos.
- **Week 9–12:** "How Much Money I Made Selling CNC Lake Maps" revenue reveal. Process optimization tips. Holiday gift guide featuring products.
- **Ongoing:** 2–3 TikTok/Reels per week (CNC carving clips). 1 YouTube tutorial per week. Daily engagement in CNC communities.

---

## 18. Technical Specifications & SVG Output Reference

### SVG File Structure

```xml
<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg"
     width="406.4mm" height="508.0mm"
     viewBox="0 0 406.4 508.0">

  <!-- MapForge CNC v1.0 -->
  <!-- Location: Lake Muskoka, Ontario -->
  <!-- Board: 16" x 20" (406.4mm x 508.0mm) -->
  <!-- Nodes: 847 | Paths: 3 | Layers: 4 -->
  <!-- Data: OpenStreetMap (ODbL) -->

  <!-- Layer: board_outline -->
  <g id="board_outline">
    <rect width="406.4" height="508.0"
          fill="none" stroke="#ccc" stroke-width="0.25"
          stroke-dasharray="4,4"/>
  </g>

  <!-- Layer: geography_outline -->
  <!-- Toolpath: Profile cut, 1/4" downcut, tabs -->
  <g id="geography_outline">
    <path d="M203.2,45.0 L210.5,47.3 ... Z"
          fill="none" stroke="#1a1a1a" stroke-width="0.5"
          stroke-linejoin="round"/>
  </g>

  <!-- Layer: text_primary -->
  <!-- Toolpath: V-carve, 60deg V-bit -->
  <g id="text_primary">
    <text x="203.2" y="475"
          text-anchor="middle" font-family="Arial"
          font-size="14" font-weight="bold"
          fill="#1a1a1a">Lake Muskoka</text>
  </g>

  <!-- Layer: text_coordinates -->
  <g id="text_coordinates">
    <text x="203.2" y="492"
          text-anchor="middle" font-family="Arial"
          font-size="6" fill="#666">45.0312°N, 79.6089°W</text>
  </g>
</svg>
```

### Board Size Reference

| Label | Inches | Millimeters | Best For |
|---|---|---|---|
| Small | 12" × 16" | 304.8 × 406.4 mm | Silhouette signs, name signs |
| Medium | 16" × 20" | 406.4 × 508.0 mm | Lake maps, city maps (most popular) |
| Large | 20" × 24" | 508.0 × 609.6 mm | Premium lake maps, topo maps |
| XL | 24" × 32" | 609.6 × 812.8 mm | Statement pieces, national parks |
| Max (Journeyman) | 32" × 48" | 812.8 × 1219.2 mm | Full bed, large installations |

### Performance Targets

| Operation | Target | Notes |
|---|---|---|
| Location search | < 1 second | Nominatim API response time |
| Geometry fetch (cached) | < 200ms | From Supabase/Redis cache |
| Geometry fetch (new, simple) | < 3 seconds | Nominatim inline polygon |
| Geometry fetch (new, complex) | < 8 seconds | Overpass API for large relations |
| SVG generation | < 500ms | After geometry is fetched |
| Preview render (iOS) | < 100ms | CoreGraphics path rendering |
| SVG file size | < 500 KB | Typical lake map; < 2MB for complex city maps |
| End-to-end (search to export) | < 60 seconds | Including user customization time |

---

## 19. Competitive Analysis

| Competitor | What They Do | Price | MapForge Advantage |
|---|---|---|---|
| Etsy SVG sellers | Individual sellers listing hand-made lake map SVGs | $8–$25/file | MapForge covers ANY location instantly. Most sellers have < 50 files. |
| Lake Art Co / similar | Custom lake map companies (physical products) | $100–$400/piece | MapForge enables you to compete on physical products AND sell files. |
| Gaia GPS / CalTopo | Outdoor GPS/topo apps (not CNC-focused) | $30–$40/yr | Not CNC-optimized. No SVG export. Different market. |
| QGIS (manual process) | Free GIS software for manual SVG creation | Free | MapForge automates 30–90 min of QGIS work into 60 seconds. |
| Easel / Carbide Create | CNC CAM software with basic design | Free–$300 | No geographic data integration. MapForge feeds into these tools. |

> **MapForge CNC has NO direct competitor.** No existing tool combines real-time geographic data fetching, CNC-optimized geometry processing, and SVG generation into a single app. The closest alternatives are either manual processes (QGIS) or pre-made file marketplaces with limited coverage. MapForge eliminates the gap between geographic data and CNC production.

---

## 20. Appendix: SVG Code Examples

### Example: Province Silhouette (Outline Style)

```xml
<svg width="304.8mm" height="406.4mm" viewBox="0 0 304.8 406.4">
  <g id="geography_outline">
    <path d="M152.4,30.0 L158.2,32.1 L165.0,28.7 ... Z"
          fill="none" stroke="#1a1a1a" stroke-width="0.5"
          stroke-linejoin="round"/>
  </g>
  <g id="text_primary">
    <text x="152.4" y="380"
          text-anchor="middle" font-family="Arial"
          font-size="16" font-weight="bold">NOVA SCOTIA</text>
  </g>
</svg>
```

### Example: Lake Map (Filled Style with Depth Bands)

```xml
<svg width="406.4mm" height="508.0mm" viewBox="0 0 406.4 508.0">
  <g id="geography_fill">
    <!-- Outer shoreline -->
    <path d="M200,50 L215,55 L230,48 ... Z"
          fill="#2a2a2a" stroke="#1a1a1a" stroke-width="0.5"/>
  </g>
  <g id="depth_bands">
    <!-- Depth band 1: 0-5m (pocket depth: 1mm) -->
    <path d="M205,60 L210,63 ... Z" fill="#3a3a3a" stroke="none"/>
    <!-- Depth band 2: 5-10m (pocket depth: 2mm) -->
    <path d="M208,65 L212,68 ... Z" fill="#4a4a4a" stroke="none"/>
    <!-- Depth band 3: 10-20m (pocket depth: 3mm) -->
    <path d="M210,70 L214,73 ... Z" fill="#5a5a5a" stroke="none"/>
  </g>
  <g id="text_primary">
    <text x="203.2" y="480"
          text-anchor="middle" font-family="Arial"
          font-size="14" font-weight="bold">LAKE MUSKOKA</text>
  </g>
</svg>
```

### Example: City Street Map (Engraved Style)

```xml
<svg width="406.4mm" height="406.4mm" viewBox="0 0 406.4 406.4">
  <g id="geography_outline">
    <!-- City boundary -->
    <path d="M50,50 L350,50 L350,350 L50,350 Z"
          fill="none" stroke="#1a1a1a" stroke-width="0.5"/>
  </g>
  <g id="detail_lines">
    <!-- Major roads (engrave, 0.05" depth) -->
    <path d="M100,50 L100,350" fill="none" stroke="#333" stroke-width="0.8"/>
    <path d="M200,50 L200,350" fill="none" stroke="#333" stroke-width="0.8"/>
    <!-- Minor roads (engrave, 0.03" depth) -->
    <path d="M150,100 L250,100" fill="none" stroke="#555" stroke-width="0.3"/>
  </g>
  <g id="text_primary">
    <text x="203.2" y="390"
          text-anchor="middle" font-family="Arial"
          font-size="14" font-weight="bold">HALIFAX</text>
  </g>
</svg>
```

---

*End of MapForge CNC Product Story Bible — Version 1.0*

*Generated March 15, 2026. This is a living document and will be updated as the product evolves.*
