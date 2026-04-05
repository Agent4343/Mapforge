import { useState } from "react";

const FEATURES = [
  {
    title: "Wall Art Print Files",
    desc: "High-resolution PNG files at 300 or 600 DPI. Print at home, send to a print shop, or upload to a print-on-demand service.",
  },
  {
    title: "CNC-Ready SVG & DXF",
    desc: "Clean vector files with proper layers, toolpath metadata, and 0.01mm precision. Import directly into VCarve Pro, Easel, or any CNC software.",
  },
  {
    title: "13 Color Themes",
    desc: "From minimalist B&W to Midnight Blue, Rose Gold, and Navy Gold. Choose the perfect palette for any room or gift.",
  },
  {
    title: "Any City on Earth",
    desc: "Search for any city and get a beautiful street map. The dense street grid creates stunning visual texture unique to each location.",
  },
  {
    title: "Personalize It",
    desc: "Add custom text, a meaningful subtitle like \"Where We Met\", heart markers, and GPS coordinates. Make it truly yours.",
  },
  {
    title: "Multiple Sizes",
    desc: "From 8x10\" desk prints to 24x36\" statement pieces. Choose the perfect size for your space or CNC board.",
  },
];

const SHOWCASE = [
  { name: "New York City", type: "Wall Art", size: '18x24"', price: "$15.99" },
  { name: "Toronto", type: "Wall Art", size: '18x24"', price: "$15.99" },
  { name: "Miami", type: "CNC", size: '24x36"', price: "$19.99" },
  { name: "London", type: "Wall Art", size: '16x20"', price: "$15.99" },
];

export default function LandingPage({ onGetStarted, onSignIn }) {
  return (
    <div className="landing">
      {/* Hero */}
      <section className="landing-hero">
        <div className="landing-hero-content">
          <h1>
            City Street Map<br />
            <span className="text-crimson">Art & CNC Files</span>
          </h1>
          <p className="landing-hero-sub">
            Create stunning city street map art — as print-ready wall art or
            CNC-ready vector files for wood carving. Perfect for housewarming gifts,
            wedding keepsakes, or your workshop. Starting at $7.99.
          </p>
          <div className="landing-hero-actions">
            <button className="btn btn-primary btn-lg" onClick={onGetStarted}>
              Start Designing
            </button>
            <button className="btn btn-secondary btn-lg" onClick={onSignIn}>
              Sign In
            </button>
          </div>
          <p className="landing-hero-note">
            Design for free. Only pay when you love it.
          </p>
        </div>
      </section>

      {/* Two product paths */}
      <section className="landing-section">
        <h2>Two Ways to Create</h2>
        <div className="landing-steps">
          <div className="landing-step">
            <div className="landing-step-num">&#128444;</div>
            <h3>Wall Art Prints</h3>
            <p>Download high-resolution PNG files ready for printing. Frame it, gift it, or sell it on Etsy. Professional quality at 300 or 600 DPI.</p>
          </div>
          <div className="landing-step">
            <div className="landing-step-num">&#9881;</div>
            <h3>CNC Machine Files</h3>
            <p>Download clean SVG and DXF files with separated layers for VCarve Pro, Easel, or any CNC software. Cut, carve, or engrave on wood, acrylic, or metal.</p>
          </div>
        </div>
      </section>

      {/* How it works */}
      <section className="landing-section landing-section-dark">
        <h2>How It Works</h2>
        <div className="landing-steps">
          <div className="landing-step">
            <div className="landing-step-num">1</div>
            <h3>Search Your City</h3>
            <p>Find any city on Earth. The street grid is automatically fetched and rendered into beautiful map art.</p>
          </div>
          <div className="landing-step">
            <div className="landing-step-num">2</div>
            <h3>Make It Yours</h3>
            <p>Pick your size, color theme, and add a personal subtitle like "Where We Met" or a heart marker on a special spot.</p>
          </div>
          <div className="landing-step">
            <div className="landing-step-num">3</div>
            <h3>Download Your Files</h3>
            <p>Get print-ready PNGs for wall art and clean SVG/DXF vector files for CNC. Instant delivery, no waiting.</p>
          </div>
        </div>
      </section>

      {/* Pricing Examples */}
      <section className="landing-section">
        <h2>Popular Designs</h2>
        <div className="landing-showcase">
          {SHOWCASE.map((s, i) => (
            <div key={i} className="landing-showcase-card">
              <div className="landing-showcase-icon">&#9670;</div>
              <div className="landing-showcase-name">{s.name}</div>
              <div className="landing-showcase-meta">{s.type} &middot; {s.size}</div>
              <div className="landing-showcase-price">{s.price}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Features */}
      <section className="landing-section landing-section-dark">
        <h2>What You Get</h2>
        <div className="landing-features">
          {FEATURES.map((f, i) => (
            <div key={i} className="landing-feature">
              <h3>{f.title}</h3>
              <p>{f.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* CTA */}
      <section className="landing-section landing-cta">
        <h2>Ready to Create?</h2>
        <p>Design a custom city street map — for your wall or your CNC machine. Perfect for gifts, home decor, and woodworking projects.</p>
        <button className="btn btn-primary btn-lg" onClick={onGetStarted}>
          Start Designing Your Map
        </button>
      </section>

      {/* Footer */}
      <footer className="landing-footer">
        <div className="landing-footer-brand">
          <strong>Map<span className="text-crimson">Forge</span></strong>
          <span>City Street Map Art & CNC Files</span>
        </div>
        <div className="landing-footer-links">
          <span>Geographic data: OpenStreetMap (ODbL)</span>
          <span>Topo data: Natural Resources Canada</span>
        </div>
      </footer>
    </div>
  );
}
