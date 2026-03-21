import { useState } from "react";

const FEATURES = [
  {
    title: "Print-Ready Output",
    desc: "High-resolution PNG and SVG files at 300 or 600 DPI. Ready for professional printing, Etsy digital downloads, and wall art.",
  },
  {
    title: "15 Color Themes",
    desc: "From Classic to Midnight Blue, Rose Gold, and Arctic. Choose the perfect palette for any room or gift.",
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
    desc: "List your designs for sale. Stripe-powered payments with automatic seller payouts. Build a map print business.",
  },
  {
    title: "Batch Generation",
    desc: "Pro users can generate up to 50 designs at once. Scale your production with one click.",
  },
];

const SHOWCASE = [
  { name: "Lake Muskoka", type: "Lake", size: "16x20\"" },
  { name: "Banff National Park", type: "Park", size: "24x36\"" },
  { name: "Toronto", type: "City", size: "18x24\"" },
  { name: "Nova Scotia", type: "Province", size: "24x36\"" },
];

export default function LandingPage({ onGetStarted, onSignIn }) {
  return (
    <div className="landing">
      {/* Hero */}
      <section className="landing-hero">
        <div className="landing-hero-content">
          <h1>
            Turn Any Location Into a<br />
            <span className="text-crimson">Beautiful</span> Map Print
          </h1>
          <p className="landing-hero-sub">
            Generate stunning print-ready map posters from real geographic data.
            Lakes, cities, provinces, parks — or drop a pin on your family's special place.
            Perfect for Etsy shops, wall art, and personalized gifts.
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
            <p>Choose print size, color theme, typography, and border style. Add a subtitle and heart marker for gifts.</p>
          </div>
          <div className="landing-step">
            <div className="landing-step-num">3</div>
            <h3>Download & Sell</h3>
            <p>Download print-ready PNG at 300 or 600 DPI. List on Etsy, print at home, or send to a print shop.</p>
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="landing-section landing-section-dark">
        <h2>Built for Print Sellers</h2>
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
          Every design includes professional typography, themed colors, and print-ready resolution.
        </p>
      </section>

      {/* CTA */}
      <section className="landing-section landing-cta">
        <h2>Ready to Create?</h2>
        <p>Join sellers offering custom map prints on Etsy, at craft fairs, and in their shops.</p>
        <button className="btn btn-primary btn-lg" onClick={onGetStarted}>
          Create Your First Map — Free
        </button>
      </section>

      {/* Footer */}
      <footer className="landing-footer">
        <div className="landing-footer-brand">
          <strong>Map<span className="text-crimson">Forge</span></strong>
          <span>Custom Map Prints for Etsy & Wall Art</span>
        </div>
        <div className="landing-footer-links">
          <span>Geographic data: OpenStreetMap (ODbL)</span>
          <span>Topo data: Natural Resources Canada</span>
        </div>
      </footer>
    </div>
  );
}
