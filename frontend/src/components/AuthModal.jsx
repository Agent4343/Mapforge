import { useState } from "react";
import { register, login, resetPassword } from "../services/api.js";

export default function AuthModal({ onAuth, onClose }) {
  const [mode, setMode] = useState("login"); // login, register, reset
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [loading, setLoading] = useState(false);
  const [acceptTerms, setAcceptTerms] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setSuccess(null);

    try {
      if (mode === "reset") {
        await resetPassword(email, newPassword);
        setSuccess("Password reset successful. You can now sign in.");
        setMode("login");
        setPassword(newPassword);
        setNewPassword("");
      } else if (mode === "register") {
        if (!acceptTerms) {
          setError("Please accept the terms to create an account.");
          setLoading(false);
          return;
        }
        const data = await register(email, username, password);
        onAuth(data.user);
      } else {
        const data = await login(email, password);
        onAuth(data.user);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  const title = mode === "login" ? "Sign In" : mode === "register" ? "Create Account" : "Reset Password";

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <h2>{title}</h2>

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

          {mode === "login" && (
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
          )}

          {mode === "register" && (
            <div className="control-group">
              <label>Password (min 8 characters)</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={8}
              />
            </div>
          )}

          {mode === "reset" && (
            <div className="control-group">
              <label>New Password (min 8 characters)</label>
              <input
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                required
                minLength={8}
              />
            </div>
          )}

          {mode === "register" && (
            <label style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "12px", color: "var(--text-muted)", cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={acceptTerms}
                onChange={(e) => setAcceptTerms(e.target.checked)}
              />
              I agree to the Terms of Service and Privacy Policy
            </label>
          )}

          {error && <div className="error-message">{error}</div>}
          {success && <div className="success-message">{success}</div>}

          <button className="btn btn-primary btn-full" type="submit" disabled={loading}>
            {loading ? "..." : mode === "login" ? "Sign In" : mode === "register" ? "Create Account" : "Reset Password"}
          </button>
        </form>

        <div className="auth-toggle">
          {mode === "login" && (
            <>
              <button className="link-btn" onClick={() => { setMode("reset"); setError(null); setSuccess(null); }}>
                Forgot password?
              </button>
              {" \u00b7 "}
              No account?{" "}
              <button className="link-btn" onClick={() => { setMode("register"); setError(null); setSuccess(null); }}>
                Create one
              </button>
            </>
          )}
          {mode === "register" && (
            <>
              Have an account?{" "}
              <button className="link-btn" onClick={() => { setMode("login"); setError(null); setSuccess(null); }}>
                Sign in
              </button>
            </>
          )}
          {mode === "reset" && (
            <>
              Remember your password?{" "}
              <button className="link-btn" onClick={() => { setMode("login"); setError(null); setSuccess(null); }}>
                Sign in
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
