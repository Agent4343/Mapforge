import { useState } from "react";

const FEATURES = [
  {
    title: "Print-Ready Files",
    desc: "High-resolution PNG and SVG files at 300 or 600 DPI. Ready for professional printing and wall art.",
  },
  {
    title: "13 Color Themes",
    desc: "From minimalist B&W to Midnight Blue, Rose Gold, and Navy Gold. Choose the perfect palette for any room or gift.",
  },
  {
    title: "Any City on Earth",
    desc: "Search for any city and get a beautiful street map art print. The dense street grid creates stunning visual texture.",
  },
  {
    title: "Personalize It",
    desc: "Add custom text, a meaningful subtitle like \"Where We Met\", heart markers, and coordinates. Make it truly yours.",
  },
  {
    title: "Multiple Sizes",
    desc: "From 8x10\" desk prints to 24x36\" statement pieces. Choose the perfect size for your space.",
  },
  {
    title: "Instant Delivery",
    desc: "Your custom street map is generated and ready to download within seconds of ordering. No waiting.",
  },
];

const SHOWCASE = [
  { name: "New York City", type: "City", size: '18x24"', price: "$15.99" },
  { name: "Toronto", type: "City", size: '18x24"', price: "$15.99" },
  { name: "Miami", type: "City", size: '24x36"', price: "$19.99" },
  { name: "London", type: "City", size: '16x20"', price: "$15.99" },
];

export default function LandingPage({ onGetStarted, onSignIn }) {
  return (
    <div className="landing">
      {/* Hero */}
      <section className="landing-hero">
        <div className="landing-hero-content">
          <h1>
            City Street Map<br />
            <span className="text-crimson">Art Prints</span>
          </h1>
          <p className="landing-hero-sub">
            Create a stunning street map poster of the city that means the most to you.
            Perfect for housewarming gifts, wedding keepsakes, or your own wall.
            Beautifully designed and ready to print. Starting at $7.99.
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

      {/* How it works */}
      <section className="landing-section">
        <h2>How It Works</h2>
        <div className="landing-steps">
          <div className="landing-step">
            <div className="landing-step-num">1</div>
            <h3>Search Your Place</h3>
            <p>Find any lake, city, province, or park. Or drop a pin on your cottage, cabin, or the place where it all began.</p>
          </div>
          <div className="landing-step">
            <div className="landing-step-num">2</div>
            <h3>Make It Yours</h3>
            <p>Pick your size, color theme, font, and border. Add a subtitle like "Where We Met" and a heart marker.</p>
          </div>
          <div className="landing-step">
            <div className="landing-step-num">3</div>
            <h3>Order & Download</h3>
            <p>Pay securely and instantly download your print-ready files. Print at home or send to a print shop.</p>
          </div>
        </div>
      </section>

      {/* Pricing Examples */}
      <section className="landing-section landing-section-dark">
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
        <p className="landing-showcase-note">
          Price depends on map type, size, and add-ons. The price updates live as you customize.
        </p>
      </section>

      {/* Features */}
      <section className="landing-section">
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
        <p>Design a custom map print of the place that matters most. Perfect for gifts, wall art, and keepsakes.</p>
        <button className="btn btn-primary btn-lg" onClick={onGetStarted}>
          Start Designing Your Map
        </button>
      </section>

      {/* Footer */}
      <footer className="landing-footer">
        <div className="landing-footer-brand">
          <strong>Map<span className="text-crimson">Forge</span></strong>
          <span>Custom Map Art</span>
        </div>
        <div className="landing-footer-links">
          <span>Geographic data: OpenStreetMap (ODbL)</span>
          <span>Topo data: Natural Resources Canada</span>
        </div>
      </footer>
    </div>
  );
}
