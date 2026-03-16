import { useState } from "react";

const FEATURES = [
  {
    title: "CNC-Ready Output",
    desc: "SVG files with M/L/Z commands only. No curves, no cleanup. Import directly into VCarve Pro, Carbide Create, or any CAM software.",
  },
  {
    title: "DXF Export",
    desc: "Industry-standard DXF files with proper layers, units in mm, and DASHED board outlines. Ready for AutoCAD and CNC controllers.",
  },
  {
    title: "Any Location on Earth",
    desc: "Lakes, provinces, cities, parks, communities. Search by name or drop a pin on your family cabin, cottage, or favorite spot.",
  },
  {
    title: "Product Mockups",
    desc: "Auto-generated PNG thumbnails with warm wood-tone backgrounds. Perfect for Etsy listings and social media.",
  },
  {
    title: "Seller Marketplace",
    desc: "List your designs for sale. Stripe-powered payments with automatic seller payouts. Build a CNC design business.",
  },
  {
    title: "Batch Generation",
    desc: "Pro users can generate up to 50 designs at once. Scale your production with one click.",
  },
];

const SHOWCASE = [
  { name: "Lake Muskoka", type: "Lake", size: "16x20\"" },
  { name: "Banff National Park", type: "Park", size: "24x32\"" },
  { name: "Toronto", type: "City", size: "20x24\"" },
  { name: "Nova Scotia", type: "Province", size: "32x48\"" },
];

export default function LandingPage({ onGetStarted, onSignIn }) {
  return (
    <div className="landing">
      {/* Hero */}
      <section className="landing-hero">
        <div className="landing-hero-content">
          <h1>
            Turn Any Location Into a<br />
            <span className="text-crimson">CNC-Ready</span> Wood Map
          </h1>
          <p className="landing-hero-sub">
            Generate production-quality SVG and DXF files from real geographic data.
            Lakes, cities, provinces, parks — or drop a pin on your family's special place.
            Import directly into VCarve Pro, Carbide Create, or any CAM software.
          </p>
          <div className="landing-hero-actions">
            <button className="btn btn-primary btn-lg" onClick={onGetStarted}>
              Start Creating — Free
            </button>
            <button className="btn btn-secondary btn-lg" onClick={onSignIn}>
              Sign In
            </button>
          </div>
          <p className="landing-hero-note">
            No credit card required. Generate your first map in under 60 seconds.
          </p>
        </div>
      </section>

      {/* How it works */}
      <section className="landing-section">
        <h2>How It Works</h2>
        <div className="landing-steps">
          <div className="landing-step">
            <div className="landing-step-num">1</div>
            <h3>Search or Pin</h3>
            <p>Search any lake, city, province, or park. Or drop a pin on your cottage, cabin, or favorite place.</p>
          </div>
          <div className="landing-step">
            <div className="landing-step-num">2</div>
            <h3>Customize</h3>
            <p>Choose board size, cut style (outline, filled, engraved), add text and coordinates. Preview instantly.</p>
          </div>
          <div className="landing-step">
            <div className="landing-step-num">3</div>
            <h3>Export & Cut</h3>
            <p>Download SVG or DXF. Import into your CNC software. Cut, engrave, or pocket on real wood.</p>
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="landing-section landing-section-dark">
        <h2>Built for CNC Makers</h2>
        <div className="landing-features">
          {FEATURES.map((f, i) => (
            <div key={i} className="landing-feature">
              <h3>{f.title}</h3>
              <p>{f.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Showcase */}
      <section className="landing-section">
        <h2>What You Can Make</h2>
        <div className="landing-showcase">
          {SHOWCASE.map((s, i) => (
            <div key={i} className="landing-showcase-card">
              <div className="landing-showcase-icon">&#9670;</div>
              <div className="landing-showcase-name">{s.name}</div>
              <div className="landing-showcase-meta">{s.type} &middot; {s.size}</div>
            </div>
          ))}
        </div>
        <p className="landing-showcase-note">
          Every design includes proper toolpath comments, organized layers, closed paths, and CNC metadata.
        </p>
      </section>

      {/* CTA */}
      <section className="landing-section landing-cta">
        <h2>Ready to Build?</h2>
        <p>Join makers selling custom wood maps on Etsy, at craft fairs, and in their shops.</p>
        <button className="btn btn-primary btn-lg" onClick={onGetStarted}>
          Create Your First Map — Free
        </button>
      </section>

      {/* Footer */}
      <footer className="landing-footer">
        <div className="landing-footer-brand">
          <strong>Map<span className="text-crimson">Forge</span> CNC</strong>
          <span>Geographic SVG Generator for CNC Routing</span>
        </div>
        <div className="landing-footer-links">
          <span>Geographic data: OpenStreetMap (ODbL)</span>
          <span>Topo data: Natural Resources Canada</span>
        </div>
      </footer>
    </div>
  );
}
