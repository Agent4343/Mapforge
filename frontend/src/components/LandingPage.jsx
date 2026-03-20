const FEATURES = [
  {
    title: "Any Place That Matters",
    desc: "Search any city, neighborhood, lake, or park in the world. Or drop a pin on the exact spot where your story began.",
  },
  {
    title: "18 Premium Themes",
    desc: "From classic cream to midnight navy. Every theme is designed for wall art — clean, elegant, and gallery-ready.",
  },
  {
    title: "Star Maps",
    desc: "Show the night sky from a specific date and place. Perfect for birthdays, anniversaries, or the night you met.",
  },
  {
    title: "Personalized Text",
    desc: "Add a city name, custom subtitle, GPS coordinates, and date. Make it uniquely yours with every detail.",
  },
  {
    title: "Instant Preview",
    desc: "See your design come to life in real time. Adjust colors, text, and layout until it's perfect.",
  },
  {
    title: "Print-Ready Quality",
    desc: "Every design exports at 300 DPI — ready for professional printing on premium paper, canvas, or framed art.",
  },
];

const OCCASIONS = [
  { emoji: "\u2764", label: "Where We Met", desc: "Anniversary & love stories" },
  { emoji: "\uD83C\uDFE0", label: "Our First Home", desc: "New homeowner gifts" },
  { emoji: "\u2B50", label: "The Night We Met", desc: "Star maps for that moment" },
  { emoji: "\uD83D\uDC76", label: "Where You Were Born", desc: "Baby milestones & nursery art" },
  { emoji: "\u2708", label: "Our Favorite Place", desc: "Travel memories & adventures" },
  { emoji: "\uD83C\uDF93", label: "Where I Grew Up", desc: "Graduation & nostalgia gifts" },
];

export default function LandingPage({ onGetStarted, onSignIn }) {
  return (
    <div className="landing">
      {/* Hero */}
      <section className="landing-hero">
        <div className="landing-hero-content">
          <h1>
            Turn Your Special Place Into<br />
            <span className="text-crimson">Beautiful Wall Art</span>
          </h1>
          <p className="landing-hero-sub">
            Design a personalized map of the place that means the most to you.
            Where you met, your first home, the city you love — turned into
            a stunning print you can hold in your hands.
          </p>
          <div className="landing-hero-actions">
            <button className="btn btn-primary btn-lg" onClick={onGetStarted}>
              Design Your Map
            </button>
            <button className="btn btn-secondary btn-lg" onClick={onSignIn}>
              Sign In
            </button>
          </div>
          <p className="landing-hero-note">
            Free to design. Save your Design ID and order your print on our Etsy shop.
          </p>
        </div>
      </section>

      {/* How it works */}
      <section className="landing-section">
        <h2>How It Works</h2>
        <div className="landing-steps">
          <div className="landing-step">
            <div className="landing-step-num">1</div>
            <h3>Design Your Map</h3>
            <p>Search any location, choose your theme, add personal text. See your creation instantly in our live preview.</p>
          </div>
          <div className="landing-step">
            <div className="landing-step-num">2</div>
            <h3>Save & Get Your Design ID</h3>
            <p>Save your design and receive a unique Design ID (like MS-A3F8K2). This ID holds your entire design.</p>
          </div>
          <div className="landing-step">
            <div className="landing-step-num">3</div>
            <h3>Order on Etsy</h3>
            <p>Visit our Etsy shop, choose your print size, and enter your Design ID at checkout. We print and ship directly to you.</p>
          </div>
        </div>
      </section>

      {/* Perfect For */}
      <section className="landing-section landing-section-dark">
        <h2>Perfect For Every Occasion</h2>
        <div className="landing-features">
          {OCCASIONS.map((o, i) => (
            <div key={i} className="landing-feature">
              <div style={{ fontSize: "24px", marginBottom: "6px" }}>{o.emoji}</div>
              <h3>{o.label}</h3>
              <p>{o.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Features */}
      <section className="landing-section">
        <h2>Design Tools</h2>
        <div className="landing-features">
          {FEATURES.map((f, i) => (
            <div key={i} className="landing-feature">
              <h3>{f.title}</h3>
              <p>{f.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Pricing */}
      <section className="landing-section landing-section-dark">
        <h2>Simple Pricing</h2>
        <div className="landing-steps">
          <div className="landing-step">
            <div className="landing-step-num" style={{ background: "var(--crimson)" }}>$</div>
            <h3>8x10" Print</h3>
            <p style={{ fontSize: "20px", fontWeight: "bold" }}>$18.99</p>
          </div>
          <div className="landing-step">
            <div className="landing-step-num" style={{ background: "var(--crimson)" }}>$</div>
            <h3>12x18" Print</h3>
            <p style={{ fontSize: "20px", fontWeight: "bold" }}>$24.99</p>
          </div>
          <div className="landing-step">
            <div className="landing-step-num" style={{ background: "var(--crimson)" }}>$</div>
            <h3>16x20" Print</h3>
            <p style={{ fontSize: "20px", fontWeight: "bold" }}>$29.99</p>
          </div>
        </div>
        <p style={{ textAlign: "center", color: "var(--text-secondary)", marginTop: "12px", fontSize: "13px" }}>
          Premium matte paper. Free shipping on orders over $30.
        </p>
      </section>

      {/* CTA */}
      <section className="landing-section landing-cta">
        <h2>Create Something Meaningful</h2>
        <p>The perfect gift isn't bought — it's designed. Start creating your custom map print today.</p>
        <button className="btn btn-primary btn-lg" onClick={onGetStarted}>
          Design Your Map
        </button>
      </section>

      {/* Footer */}
      <footer className="landing-footer">
        <div className="landing-footer-brand">
          <strong>Map<span className="text-crimson">Story</span> Studio</strong>
          <span>Custom Map Prints for Life's Special Places</span>
        </div>
        <div className="landing-footer-links">
          <span>Geographic data: OpenStreetMap (ODbL)</span>
        </div>
      </footer>
    </div>
  );
}
