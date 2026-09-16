import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { ApiError, api } from "../api";

interface Props {
  email: string;
  displayName: string | null;
  onDisplayNameChange: (displayName: string | null) => void;
}

export function AccountTab({ email, displayName, onDisplayNameChange }: Props) {
  const [nameInput, setNameInput] = useState(displayName ?? "");
  const [nameError, setNameError] = useState<string | null>(null);
  const [nameSaved, setNameSaved] = useState(false);
  const [savingName, setSavingName] = useState(false);

  // ESPN connection. The cookies themselves are never readable back from
  // the server, so this only ever tracks connected/not and whatever the
  // user is currently typing.
  const [espnConnected, setEspnConnected] = useState(false);
  const [espnS2, setEspnS2] = useState("");
  const [swid, setSwid] = useState("");
  const [espnError, setEspnError] = useState<string | null>(null);
  const [espnSaved, setEspnSaved] = useState<string | null>(null);
  const [savingEspn, setSavingEspn] = useState(false);

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let ignore = false;
    api
      .getEspnCredentials()
      .then((status) => {
        if (!ignore) setEspnConnected(status.connected);
      })
      .catch(() => {
        // Non-critical: the section still works, it just starts out
        // assuming nothing is connected.
      });
    return () => {
      ignore = true;
    };
  }, []);

  async function handleSaveEspn(e: FormEvent) {
    e.preventDefault();
    setEspnError(null);
    setEspnSaved(null);
    setSavingEspn(true);
    try {
      const status = await api.setEspnCredentials(espnS2, swid);
      setEspnConnected(status.connected);
      setEspnS2("");
      setSwid("");
      setEspnSaved(
        status.connected
          ? "Connected. Your real ESPN claims now show under Pending Moves on the Waivers tab."
          : "Disconnected."
      );
    } catch (err) {
      setEspnError(err instanceof ApiError ? err.message : "Failed to save your ESPN credentials.");
    } finally {
      setSavingEspn(false);
    }
  }

  async function handleDisconnectEspn() {
    setEspnError(null);
    setEspnSaved(null);
    setSavingEspn(true);
    try {
      await api.setEspnCredentials("", "");
      setEspnConnected(false);
      setEspnS2("");
      setSwid("");
      setEspnSaved("Disconnected.");
    } catch (err) {
      setEspnError(err instanceof ApiError ? err.message : "Failed to disconnect.");
    } finally {
      setSavingEspn(false);
    }
  }

  async function handleSaveDisplayName(e: FormEvent) {
    e.preventDefault();
    setNameError(null);
    setNameSaved(false);
    setSavingName(true);
    try {
      const updated = await api.updateDisplayName(nameInput);
      onDisplayNameChange(updated.display_name);
      setNameInput(updated.display_name ?? "");
      setNameSaved(true);
    } catch (err) {
      setNameError(err instanceof ApiError ? err.message : "Failed to save display name.");
    } finally {
      setSavingName(false);
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSuccess(false);

    if (newPassword !== confirmPassword) {
      setError("New passwords don't match.");
      return;
    }

    setSaving(true);
    try {
      await api.changePassword(currentPassword, newPassword);
      setSuccess(true);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to change password.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="panel">
      <h2>Account</h2>
      <p className="hint">
        Signed in as {email}. Changing your password doesn't sign you out anywhere else you're currently logged
        in &mdash; that happens naturally once your existing session expires.
      </p>

      <form onSubmit={handleSaveDisplayName} className="form-row">
        <label>
          Display name
          <input
            type="text"
            maxLength={50}
            value={nameInput}
            onChange={(e) => setNameInput(e.target.value)}
            placeholder={email}
          />
        </label>
        <button type="submit" disabled={savingName}>
          {savingName ? "Saving..." : "Save"}
        </button>
      </form>
      {nameError && <p className="error">{nameError}</p>}
      {nameSaved && <p className="success">Saved &mdash; shown in place of your email at the top of the page.</p>}
      <p className="hint">Leave it blank to show your email there instead.</p>

      <div className="espn-connect">
        <h3>
          ESPN Account{" "}
          <span className={espnConnected ? "success" : "hint"} style={{ fontSize: "0.8rem" }}>
            {espnConnected ? "Connected" : "Not connected"}
          </span>
        </h3>
        <p className="hint">
          Connecting your ESPN account lets this app read the waiver claims and trade offers you've actually
          submitted in ESPN &mdash; they appear under <strong>Pending Moves</strong> on the Waivers tab &mdash; and
          lets you sync private leagues of your own. ESPN only shows that data to the account it belongs to, which is
          why it needs your cookies and not just a league ID. Read-only: nothing here ever submits or cancels a claim
          for you.
        </p>
        <p className="hint">
          To find them: sign in at fantasy.espn.com, open your browser's developer tools &rarr; Application (or
          Storage) &rarr; Cookies &rarr; espn.com, and copy the values of <code>espn_s2</code> and <code>SWID</code>.
          They're as sensitive as your ESPN password, they're stored only on this server, and they're never sent back
          to the browser once saved. ESPN expires them every few weeks &mdash; re-paste them when claims stop showing
          up.
        </p>
        <form onSubmit={handleSaveEspn} style={{ maxWidth: "420px" }}>
          <div className="form-row" style={{ flexDirection: "column", alignItems: "stretch" }}>
            <label>
              espn_s2
              <input
                type="password"
                value={espnS2}
                onChange={(e) => setEspnS2(e.target.value)}
                placeholder={espnConnected ? "Saved - paste a new value to replace it" : "AEB..."}
                autoComplete="off"
              />
            </label>
            <label>
              SWID
              <input
                type="password"
                value={swid}
                onChange={(e) => setSwid(e.target.value)}
                placeholder={espnConnected ? "Saved - paste a new value to replace it" : "{XXXXXXXX-XXXX-...}"}
                autoComplete="off"
              />
            </label>
          </div>
          {espnError && <p className="error">{espnError}</p>}
          {espnSaved && <p className="success">{espnSaved}</p>}
          <div className="form-row">
            <button type="submit" disabled={savingEspn || !espnS2.trim() || !swid.trim()}>
              {savingEspn ? "Saving..." : espnConnected ? "Replace" : "Connect"}
            </button>
            {espnConnected && (
              <button type="button" onClick={handleDisconnectEspn} disabled={savingEspn}>
                Disconnect
              </button>
            )}
          </div>
        </form>
      </div>

      <form onSubmit={handleSubmit} style={{ maxWidth: "320px" }}>
        <div className="form-row" style={{ flexDirection: "column", alignItems: "stretch" }}>
          <label>
            Current password
            <input
              type="password"
              required
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              autoComplete="current-password"
            />
          </label>
          <label>
            New password
            <input
              type="password"
              required
              minLength={8}
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              autoComplete="new-password"
            />
          </label>
          <label>
            Confirm new password
            <input
              type="password"
              required
              minLength={8}
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              autoComplete="new-password"
            />
          </label>
        </div>

        {error && <p className="error">{error}</p>}
        {success && <p className="success">Password updated.</p>}

        <button type="submit" disabled={saving}>
          {saving ? "Saving..." : "Change Password"}
        </button>
      </form>
    </div>
  );
}
