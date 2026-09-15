import { useEffect, useState } from "react";
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
                <tr key={u.id}>
                  <td>{u.email}</td>
                  <td className="hint">{new Date(u.created_at).toLocaleDateString()}</td>
                  <td className="num">{u.league_count}</td>
                  <td>
                    {u.id === currentUserId ? (
                      <span className="hint">(you)</span>
                    ) : (
                      <button onClick={() => handleDelete(u)} disabled={pendingDeleteId === u.id}>
                        {pendingDeleteId === u.id ? "Removing..." : "Remove"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
