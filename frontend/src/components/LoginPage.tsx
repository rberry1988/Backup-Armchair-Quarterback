import { useState } from "react";
import type { FormEvent } from "react";
import { ApiError, api, setToken } from "../api";

interface Props {
  onLoggedIn: () => void;
}

export function LoginPage({ onLoggedIn }: Props) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showForgotHint, setShowForgotHint] = useState(false);
  const [pending, setPending] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setPending(null);
    try {
      if (mode === "register") {
        // Registering no longer signs you in — the account is held until
        // an admin approves it, so there's nothing to log in with yet.
        const result = await api.register(email, password);
        setPending(result.detail);
        setPassword("");
        return;
      }
      const result = await api.login(email, password);
      setToken(result.access_token);
      onLoggedIn();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-screen">
      <form className="login-card" onSubmit={handleSubmit}>
        <h1>Backup Armchair Quarterback</h1>
        <p className="hint">
          {mode === "login" ? "Sign in to your account" : "Create an account — an admin approves new sign-ups"}
        </p>

        <label>
          Email
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
          />
        </label>
        <label>
          Password
          <input
            type="password"
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
          />
        </label>

        {error && <p className="error">{error}</p>}

        {pending && <p className="success">{pending}</p>}

        <button type="submit" disabled={loading}>
          {loading ? "Please wait..." : mode === "login" ? "Sign In" : "Create Account"}
        </button>

        <button
          type="button"
          className="link-button"
          onClick={() => {
            setPending(null);
            setMode(mode === "login" ? "register" : "login");
            setError(null);
          }}
        >
          {mode === "login" ? "Need an account? Register" : "Already have an account? Sign in"}
        </button>

        {mode === "login" && (
          <button type="button" className="link-button" onClick={() => setShowForgotHint((v) => !v)}>
            Forgot password?
          </button>
        )}
        {showForgotHint && (
          <p className="hint" style={{ textAlign: "center" }}>
            There's no automated reset on this app &mdash; ask whoever manages this instance to reset it for you
            from their Admin tab.
          </p>
        )}
      </form>
    </div>
  );
}
