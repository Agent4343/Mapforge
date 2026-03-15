import { useState } from "react";
import { register, login } from "../services/api.js";

export default function AuthModal({ onAuth, onClose }) {
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      let data;
      if (mode === "register") {
        data = await register(email, username, password);
      } else {
        data = await login(email, password);
      }
      onAuth(data.user);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <h2>{mode === "login" ? "Sign In" : "Create Account"}</h2>

        <form onSubmit={handleSubmit}>
          <div className="control-group">
            <label>Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>

          {mode === "register" && (
            <div className="control-group">
              <label>Username</label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                minLength={3}
              />
            </div>
          )}

          <div className="control-group">
            <label>Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
            />
          </div>

          {error && <div className="error-message">{error}</div>}

          <button className="btn btn-primary btn-full" type="submit" disabled={loading}>
            {loading ? "..." : mode === "login" ? "Sign In" : "Create Account"}
          </button>
        </form>

        <p className="auth-toggle">
          {mode === "login" ? (
            <>
              No account?{" "}
              <button className="link-btn" onClick={() => setMode("register")}>
                Create one
              </button>
            </>
          ) : (
            <>
              Have an account?{" "}
              <button className="link-btn" onClick={() => setMode("login")}>
                Sign in
              </button>
            </>
          )}
        </p>
      </div>
    </div>
  );
}
