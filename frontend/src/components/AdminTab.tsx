import { Fragment, useEffect, useState } from "react";
import type { AdminUser } from "../types";
import { ApiError, api } from "../api";

export function AdminTab({ currentUserId }: { currentUserId: number }) {
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [pendingDeleteId, setPendingDeleteId] = useState<number | null>(null);

  const [resetTargetId, setResetTargetId] = useState<number | null>(null);
  const [resetPassword, setResetPassword] = useState("");
  const [resetError, setResetError] = useState<string | null>(null);
  const [resetting, setResetting] = useState(false);
  const [justResetId, setJustResetId] = useState<number | null>(null);

  function load() {
    api
      .adminListUsers()
      .then(setUsers)
      .catch((e) => setError(e.message));
  }

  useEffect(load, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    setCreating(true);
    try {
      const created = await api.adminCreateUser(email, password);
      setUsers((prev) => (prev ? [...prev, created] : [created]));
      setEmail("");
      setPassword("");
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Failed to add person.");
    } finally {
      setCreating(false);
    }
  }

  async function handleDelete(user: AdminUser) {
    if (!window.confirm(`Remove ${user.email}? This deletes their synced leagues too.`)) return;
    setPendingDeleteId(user.id);
    setError(null);
    try {
      await api.adminDeleteUser(user.id);
      setUsers((prev) => prev?.filter((u) => u.id !== user.id) ?? null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to remove person.");
    } finally {
      setPendingDeleteId(null);
    }
  }

  function openReset(userId: number) {
    setResetTargetId(userId);
    setResetPassword("");
    setResetError(null);
    setJustResetId(null);
  }

  async function handleResetPassword(e: React.FormEvent, userId: number) {
    e.preventDefault();
    setResetError(null);
    setResetting(true);
    try {
      await api.adminResetPassword(userId, resetPassword);
      setResetTargetId(null);
      setJustResetId(userId);
    } catch (err) {
      setResetError(err instanceof ApiError ? err.message : "Failed to reset password.");
    } finally {
      setResetting(false);
    }
  }

  return (
    <div className="panel">
      <h2>Admin</h2>
      <p className="hint">
        Add or remove accounts on this instance. Removing someone deletes their synced leagues and team
        selection, but doesn't affect anyone else's data.
      </p>

      <form onSubmit={handleCreate} className="form-row">
        <label>
          Email
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="teammate@example.com"
          />
        </label>
        <label>
          Password
          <input
            type="text"
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="at least 8 characters"
          />
        </label>
        <button type="submit" disabled={creating}>
          {creating ? "Adding..." : "Add Person"}
        </button>
      </form>
      {formError && <p className="error">{formError}</p>}
      <p className="hint">
        They'll log in with this email and password directly &mdash; share it with them however you'd like.
      </p>

      {error && <p className="error">{error}</p>}
      {!users ? (
        <p>Loading...</p>
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Email</th>
                <th>Joined</th>
                <th className="num">Leagues</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <Fragment key={u.id}>
                  <tr>
                    <td>{u.email}</td>
                    <td className="hint">{new Date(u.created_at).toLocaleDateString()}</td>
                    <td className="num">{u.league_count}</td>
                    <td style={{ display: "flex", gap: "0.4rem" }}>
                      <button onClick={() => openReset(u.id)}>Reset Password</button>
                      {u.id !== currentUserId && (
                        <button onClick={() => handleDelete(u)} disabled={pendingDeleteId === u.id}>
                          {pendingDeleteId === u.id ? "Removing..." : "Remove"}
                        </button>
                      )}
                    </td>
                  </tr>
                  {resetTargetId === u.id && (
                    <tr className="bench-row">
                      <td></td>
                      <td colSpan={3}>
                        <form
                          onSubmit={(e) => handleResetPassword(e, u.id)}
                          style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}
                        >
                          <input
                            type="text"
                            required
                            minLength={8}
                            placeholder="new password, at least 8 characters"
                            value={resetPassword}
                            onChange={(e) => setResetPassword(e.target.value)}
                            autoFocus
                          />
                          <button type="submit" disabled={resetting}>
                            {resetting ? "Setting..." : "Set"}
                          </button>
                          <button type="button" onClick={() => setResetTargetId(null)}>
                            Cancel
                          </button>
                        </form>
                        {resetError && <p className="error">{resetError}</p>}
                      </td>
                    </tr>
                  )}
                  {justResetId === u.id && (
                    <tr>
                      <td></td>
                      <td colSpan={3} className="success">
                        Password reset. Share the new one with {u.email} directly.
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
