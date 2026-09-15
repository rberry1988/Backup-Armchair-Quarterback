import { useState } from "react";
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

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [saving, setSaving] = useState(false);

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
