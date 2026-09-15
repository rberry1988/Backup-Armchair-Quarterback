import { Fragment, useEffect, useRef, useState } from "react";
import type { AdminUser, FantasyProsKeyStatus, UpdateResult } from "../types";
import { ApiError, api } from "../api";

const POLL_INTERVAL_MS = 2000;
const POLL_MAX_ATTEMPTS = 90; // ~3min, matching the confirm dialog's own "can take a couple of minutes"

export function AdminTab({ currentUserId }: { currentUserId: number }) {
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [pendingDeleteId, setPendingDeleteId] = useState<number | null>(null);
  const [pendingAdminId, setPendingAdminId] = useState<number | null>(null);

  const [resetTargetId, setResetTargetId] = useState<number | null>(null);
  const [resetPassword, setResetPassword] = useState("");
  const [resetError, setResetError] = useState<string | null>(null);
  const [resetting, setResetting] = useState(false);
  const [justResetId, setJustResetId] = useState<number | null>(null);

  const [updateState, setUpdateState] = useState<"idle" | "updating" | "restarting" | "done" | "timed-out">("idle");
  const [updateResult, setUpdateResult] = useState<UpdateResult | null>(null);

  const [fpKeyStatus, setFpKeyStatus] = useState<FantasyProsKeyStatus | null>(null);
  const [fpKeyInput, setFpKeyInput] = useState("");
  const [fpKeySaving, setFpKeySaving] = useState(false);
  const [fpKeyError, setFpKeyError] = useState<string | null>(null);
  const [fpKeySaved, setFpKeySaved] = useState(false);

  // pollUntilBackUp's recursive setTimeout chain outlives this component if
  // the admin navigates to another tab while "Restarting..." is showing
  // (AdminTab unmounts entirely — see App.tsx). Without these guards it
  // keeps polling in the background and eventually calls setState on an
  // unmounted instance.
  const mountedRef = useRef(true);
  const pollTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      mountedRef.current = false;
      if (pollTimeoutRef.current) clearTimeout(pollTimeoutRef.current);
    },
    []
  );

  function load() {
    api
      .adminListUsers()
      .then(setUsers)
      .catch((e) => setError(e.message));
  }

  useEffect(load, []);

  useEffect(() => {
    let ignore = false;
    api
      .adminGetFantasyProsKeyStatus()
      .then((status) => {
        if (!ignore) setFpKeyStatus(status);
      })
      .catch(() => {
        // Non-critical status display -- leave it blank rather than
        // showing an error banner over the rest of the Admin tab.
      });
    return () => {
      ignore = true;
    };
  }, []);

  async function handleSaveFantasyProsKey(e: React.FormEvent) {
    e.preventDefault();
    setFpKeyError(null);
    setFpKeySaved(false);
    setFpKeySaving(true);
    try {
      const status = await api.adminSetFantasyProsKey(fpKeyInput);
      setFpKeyStatus(status);
      setFpKeyInput("");
      setFpKeySaved(true);
    } catch (err) {
      setFpKeyError(err instanceof ApiError ? err.message : "Failed to save the API key.");
    } finally {
      setFpKeySaving(false);
    }
  }

  async function handleClearFantasyProsKey() {
    if (!window.confirm("Clear the saved Expert Rankings API key?")) return;
    setFpKeyError(null);
    setFpKeySaved(false);
    setFpKeySaving(true);
    try {
      const status = await api.adminSetFantasyProsKey("");
      setFpKeyStatus(status);
    } catch (err) {
      setFpKeyError(err instanceof ApiError ? err.message : "Failed to clear the API key.");
    } finally {
      setFpKeySaving(false);
    }
  }

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

  async function handleToggleAdmin(user: AdminUser) {
    const makeAdmin = !user.is_admin;
    if (
      !window.confirm(
        makeAdmin
          ? `Make ${user.email} an admin? They'll be able to add/remove people and use the Update button.`
          : `Remove admin access from ${user.email}?`
      )
    )
      return;
    setPendingAdminId(user.id);
    setError(null);
    try {
      const updated = await api.adminSetAdmin(user.id, makeAdmin);
      setUsers((prev) => prev?.map((u) => (u.id === updated.id ? updated : u)) ?? null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to change admin access.");
    } finally {
      setPendingAdminId(null);
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

  async function handleUpdate() {
    if (!window.confirm("Pull the latest code, rebuild, and restart? This can take a couple of minutes."))
      return;
    setUpdateState("updating");
    setUpdateResult(null);
    try {
      const result = await api.adminUpdate();
      if (!mountedRef.current) return;
      setUpdateResult(result);
      if (result.restarting) {
        setUpdateState("restarting");
        pollUntilBackUp();
      } else {
        setUpdateState("done");
      }
    } catch (err) {
      if (!mountedRef.current) return;
      setUpdateResult({
        error: "request_failed",
        detail: err instanceof ApiError ? err.message : "The update request failed.",
      });
      setUpdateState("done");
    }
  }

  function pollUntilBackUp(attempt = 0) {
    api
      .me()
      .then(() => {
        if (mountedRef.current) setUpdateState("done");
      })
      .catch(() => {
        if (!mountedRef.current) return;
        if (attempt >= POLL_MAX_ATTEMPTS) {
          // Gave up without ever confirming the backend came back — a
          // distinct state from "done" so the UI doesn't falsely claim
          // success (see the "timed-out" branch in the render below).
          setUpdateState("timed-out");
          return;
        }
        pollTimeoutRef.current = setTimeout(() => pollUntilBackUp(attempt + 1), POLL_INTERVAL_MS);
      });
  }

  return (
    <>
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
                <th>Admin</th>
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
                    <td>
                      {u.admin_locked ? (
                        <span className="hint" title="Set via ADMIN_EMAILS in backend/.env">
                          Admin (config)
                        </span>
                      ) : u.id === currentUserId ? (
                        <span className="hint">{u.is_admin ? "Admin (you)" : "—"}</span>
                      ) : (
                        <button onClick={() => handleToggleAdmin(u)} disabled={pendingAdminId === u.id}>
                          {pendingAdminId === u.id ? "Saving..." : u.is_admin ? "Remove Admin" : "Make Admin"}
                        </button>
                      )}
                    </td>
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
                      <td colSpan={4}>
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
                      <td colSpan={4} className="success">
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

      <div className="panel" style={{ marginTop: "1.25rem" }}>
        <h2>Expert Rankings API Key</h2>
        <p className="hint">
          Powers the Expert Rankings tab and Trade Grader's expert-consensus context. Get a free key at{" "}
          <a href="https://www.fantasypros.com/api/" target="_blank" rel="noreferrer">
            fantasypros.com/api
          </a>
          . A free-tier key hard-caps every query at the top 10 results, so this only ever covers elite/startable
          players &mdash; everything else works fine without it.
        </p>
        <p className="hint">
          {fpKeyStatus === null
            ? "Loading..."
            : fpKeyStatus.configured
              ? fpKeyStatus.source === "config"
                ? "Currently set via FANTASYPROS_API_KEY in backend/.env."
                : "Currently set (saved from this tab)."
              : "Not set — Expert Rankings and Trade Grader's expert context are unavailable."}
        </p>
        <form onSubmit={handleSaveFantasyProsKey} className="form-row">
          <label>
            API Key
            <input
              type="text"
              required
              value={fpKeyInput}
              onChange={(e) => setFpKeyInput(e.target.value)}
              placeholder="paste your FantasyPros API key"
            />
          </label>
          <button type="submit" disabled={fpKeySaving}>
            {fpKeySaving ? "Saving..." : "Save"}
          </button>
          {fpKeyStatus?.source === "database" && (
            <button type="button" onClick={handleClearFantasyProsKey} disabled={fpKeySaving}>
              Clear
            </button>
          )}
        </form>
        {fpKeyError && <p className="error">{fpKeyError}</p>}
        {fpKeySaved && <p className="success">Saved &mdash; takes effect on the next league sync.</p>}
      </div>

      <div className="panel" style={{ marginTop: "1.25rem" }}>
        <h2>Update</h2>
        <p className="hint">
          Pulls the latest committed code, reinstalls any new dependencies, rebuilds the frontend, and restarts
          &mdash; the same steps as running install.sh by hand. Only does anything if there's a new commit to
          pull; disabled entirely unless <code>ENABLE_SELF_UPDATE=true</code> is set in <code>backend/.env</code>.
        </p>
        <button onClick={handleUpdate} disabled={updateState === "updating" || updateState === "restarting"}>
          {updateState === "updating"
            ? "Pulling and rebuilding..."
            : updateState === "restarting"
              ? "Restarting..."
              : "Update App"}
        </button>

        {updateResult && (
          <div style={{ marginTop: "0.75rem" }}>
            {updateResult.error === "request_failed" && <p className="error">{updateResult.detail}</p>}
            {updateResult.error === "not_a_git_checkout" && <p className="error">{updateResult.detail}</p>}
            {updateResult.error &&
              !["request_failed", "not_a_git_checkout"].includes(updateResult.error) && (
                <p className="error">
                  Failed at: {updateResult.error.replace(/_/g, " ")}. See the step output below.
                </p>
              )}
            {updateResult.changed === false && <p className="success">Already up to date &mdash; nothing to do.</p>}
            {updateResult.changed && updateResult.restarting && updateState === "restarting" && (
              <p className="hint">Update applied. Waiting for the backend to come back...</p>
            )}
            {updateResult.changed && updateResult.restarting && updateState === "done" && (
              <p className="success">
                Update complete and the app has restarted.{" "}
                <button type="button" onClick={() => window.location.reload()}>
                  Reload page
                </button>
              </p>
            )}
            {updateResult.changed && updateResult.restarting && updateState === "timed-out" && (
              <p className="error">
                Still couldn't reach the backend after a few minutes &mdash; it may still be restarting, or may
                have failed to come back up. Check <code>systemctl status</code> / the service logs, then{" "}
                <button type="button" onClick={() => window.location.reload()}>
                  reload the page
                </button>{" "}
                to check.
              </p>
            )}

            {updateResult.steps && updateResult.steps.some((s) => !s.ok) && (
              <div className="table-scroll" style={{ marginTop: "0.5rem" }}>
                <table>
                  <thead>
                    <tr>
                      <th>Step</th>
                      <th>Result</th>
                      <th>Output</th>
                    </tr>
                  </thead>
                  <tbody>
                    {updateResult.steps.map((step, i) => (
                      <tr key={i}>
                        <td className="hint">{step.command}</td>
                        <td className={step.ok ? "success" : "error"}>{step.ok ? "ok" : "failed"}</td>
                        <td>
                          <pre style={{ whiteSpace: "pre-wrap", margin: 0, fontSize: "0.75rem" }}>
                            {step.output || "(no output)"}
                          </pre>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>
    </>
  );
}
