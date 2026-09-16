import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { ApiError, api } from "../api";
import { ESPN_BOOKMARKLET, parseEspnCookies } from "../espnCookies";

interface Props {
  email: string;
  displayName: string | null;
  // Connecting an ESPN account only unlocks premium features, so the whole
  // section is hidden for basic accounts — and its endpoints 403 for them
  // too, so this isn't the only thing keeping them out.
  isPremium: boolean;
  onDisplayNameChange: (displayName: string | null) => void;
}

export function AccountTab({ email, displayName, isPremium, onDisplayNameChange }: Props) {
  const [nameInput, setNameInput] = useState(displayName ?? "");
  const [nameError, setNameError] = useState<string | null>(null);
  const [nameSaved, setNameSaved] = useState(false);
  const [savingName, setSavingName] = useState(false);

  // ESPN connection. The cookies themselves are never readable back from
  // the server, so this only ever tracks connected/not and whatever the
  // user is currently typing.
  const [espnConnected, setEspnConnected] = useState(false);
  const [espnPaste, setEspnPaste] = useState("");
  const [espnS2, setEspnS2] = useState("");
  const [swid, setSwid] = useState("");
  const [espnError, setEspnError] = useState<string | null>(null);
  const [espnSaved, setEspnSaved] = useState<string | null>(null);
  const [savingEspn, setSavingEspn] = useState(false);
  const [bookmarkletCopied, setBookmarkletCopied] = useState(false);

  // Notifications. As with the ESPN cookies, the saved URL is never
  // readable back from the server -- only whether one exists.
  const [webhookConfigured, setWebhookConfigured] = useState(false);
  const [webhookService, setWebhookService] = useState<string | null>(null);
  const [webhookInput, setWebhookInput] = useState("");
  const [webhookError, setWebhookError] = useState<string | null>(null);
  const [webhookSaved, setWebhookSaved] = useState<string | null>(null);
  const [savingWebhook, setSavingWebhook] = useState(false);
  // React 19 refuses to render a javascript: href, which is exactly what a
  // bookmarklet is, so the attribute is set on the DOM node directly. The
  // link is there to be dragged to a bookmarks bar, not clicked here —
  // clicking it on this page would find no ESPN cookies and say so.
  const bookmarkletRef = useRef<HTMLAnchorElement>(null);

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!isPremium) return;  // the endpoint would 403 anyway
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
  }, [isPremium]);

  useEffect(() => {
    // Re-run on isPremium so the href is set if the section appears later;
    // the ref is null on the renders where it isn't shown at all.
    bookmarkletRef.current?.setAttribute("href", ESPN_BOOKMARKLET);
  }, [isPremium]);

  useEffect(() => {
    if (!isPremium) return;
    let ignore = false;
    api
      .getWebhook()
      .then((s) => {
        if (ignore) return;
        setWebhookConfigured(s.configured);
        setWebhookService(s.service);
      })
      .catch(() => {
        // Non-critical: the section still works, it just starts out
        // assuming nothing is configured.
      });
    return () => {
      ignore = true;
    };
  }, [isPremium]);

  async function handleSaveWebhook(e: FormEvent) {
    e.preventDefault();
    setWebhookError(null);
    setWebhookSaved(null);
    setSavingWebhook(true);
    try {
      const status = await api.setWebhook(webhookInput);
      setWebhookConfigured(status.configured);
      setWebhookService(status.service);
      setWebhookInput("");
      setWebhookSaved(status.configured ? `Saved. Notifications will go to ${status.service}.` : "Notifications off.");
    } catch (err) {
      setWebhookError(err instanceof ApiError ? err.message : "Failed to save that webhook.");
    } finally {
      setSavingWebhook(false);
    }
  }

  async function handleTestWebhook() {
    setWebhookError(null);
    setWebhookSaved(null);
    setSavingWebhook(true);
    try {
      await api.testWebhook();
      setWebhookSaved("Sent — check your channel.");
    } catch (err) {
      setWebhookError(err instanceof ApiError ? err.message : "Couldn't send a test message.");
    } finally {
      setSavingWebhook(false);
    }
  }

  async function handleCopyBookmarklet() {
    try {
      await navigator.clipboard.writeText(ESPN_BOOKMARKLET);
      setBookmarkletCopied(true);
      window.setTimeout(() => setBookmarkletCopied(false), 4000);
    } catch {
      // Clipboard access can be refused (insecure origin, or the user said
      // no). Dragging the link still works, so this isn't worth an error.
      setBookmarkletCopied(false);
    }
  }

  async function handleSaveEspn(e: FormEvent) {
    e.preventDefault();
    setEspnError(null);
    setEspnSaved(null);

    // Whatever was pasted wins; the two fields below it are the fallback
    // for copying each value out of devtools by hand. Parsed here rather
    // than on the server so a full cookie dump — which carries plenty of
    // unrelated ESPN cookies — never leaves the browser.
    const pasted = parseEspnCookies(espnPaste);
    const resolvedS2 = pasted.espnS2 || espnS2.trim();
    const resolvedSwid = pasted.swid || swid.trim();
    if (!resolvedS2 || !resolvedSwid) {
      setEspnError(
        resolvedS2 || resolvedSwid
          ? `Found ${resolvedS2 ? "espn_s2" : "SWID"} but not ${resolvedS2 ? "SWID" : "espn_s2"}. ESPN needs both.`
          : "Couldn't find espn_s2 and SWID in that. Run the bookmarklet on fantasy.espn.com and paste what it copies."
      );
      return;
    }

    setSavingEspn(true);
    try {
      const status = await api.setEspnCredentials(resolvedS2, resolvedSwid);
      setEspnConnected(status.connected);
      setEspnPaste("");
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
      setEspnPaste("");
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

      {isPremium && (
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
            why it needs your session and not just a league ID. Read-only: nothing here ever submits or cancels a claim
            for you.
          </p>

          <ol className="espn-steps">
            <li>
              Drag this to your bookmarks bar (or{" "}
              <button type="button" className="link-button" onClick={handleCopyBookmarklet}>
                copy it
              </button>{" "}
              and paste it in as a new bookmark's URL):
              <div className="bookmarklet-row">
                {/* href is set in an effect - see bookmarkletRef. */}
                <a ref={bookmarkletRef} className="bookmarklet" onClick={(e) => e.preventDefault()}>
                  Get ESPN cookies
                </a>
                {bookmarkletCopied && <span className="success">Copied</span>}
              </div>
            </li>
            <li>
              Open <strong>fantasy.espn.com</strong>, signed in, and click that bookmark there. It copies your{" "}
              <code>espn_s2</code> and <code>SWID</code> to your clipboard and sends them nowhere.
            </li>
            <li>Come back here, paste, and hit {espnConnected ? "Replace" : "Connect"}.</li>
          </ol>

          <form onSubmit={handleSaveEspn} style={{ maxWidth: "460px" }}>
            <label className="espn-paste-label">
              Paste from ESPN
              <textarea
                rows={3}
                value={espnPaste}
                onChange={(e) => setEspnPaste(e.target.value)}
                placeholder={espnConnected ? "Saved - paste again to replace it" : "espn_s2=...; SWID={...}"}
                autoComplete="off"
                spellCheck={false}
              />
            </label>
            <p className="hint">
              A whole cookie dump is fine too &mdash; only <code>espn_s2</code> and <code>SWID</code> are picked out,
              here in your browser, and only those two are sent to the server.
            </p>

            <details className="espn-manual">
              <summary>Enter them separately instead</summary>
              <p className="hint">
                Sign in at fantasy.espn.com, open your browser's developer tools &rarr; Application (or Storage) &rarr;
                Cookies &rarr; espn.com, and copy each value.
              </p>
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
            </details>

            {espnError && <p className="error">{espnError}</p>}
            {espnSaved && <p className="success">{espnSaved}</p>}
            <div className="form-row">
              <button
                type="submit"
                disabled={savingEspn || (!espnPaste.trim() && !(espnS2.trim() && swid.trim()))}
              >
                {savingEspn ? "Saving..." : espnConnected ? "Replace" : "Connect"}
              </button>
              {espnConnected && (
                <button type="button" onClick={handleDisconnectEspn} disabled={savingEspn}>
                  Disconnect
                </button>
              )}
            </div>
          </form>
          <p className="hint">
            These are as sensitive as your ESPN password. They're stored only on this server, used only for your own
            requests, and never sent back to the browser once saved. ESPN expires them every few weeks &mdash; re-run
            the bookmarklet when claims stop showing up.
          </p>
        </div>
      )}

      {isPremium && (
        <div className="espn-connect notify-panel">
          <h3>
            Notifications{" "}
            <span className={webhookConfigured ? "success" : "hint"} style={{ fontSize: "0.8rem" }}>
              {webhookConfigured ? `On \u2014 ${webhookService}` : "Off"}
            </span>
          </h3>
          <p className="hint">
            Paste a Discord or Slack incoming webhook URL and this app will message you when a starter is ruled out
            or hits a bye, and when your league changes &mdash; the moments you'd otherwise find out about by
            happening to open the app. Only those two services are accepted, over https.
          </p>
          <p className="hint">
            In Discord: <strong>Server Settings &rarr; Integrations &rarr; Webhooks &rarr; New Webhook &rarr; Copy
            Webhook URL</strong>. In Slack: create an <strong>Incoming Webhook</strong> app for the channel you want.
          </p>
          <form onSubmit={handleSaveWebhook} style={{ maxWidth: "460px" }}>
            <label className="espn-paste-label">
              Webhook URL
              <input
                type="password"
                value={webhookInput}
                onChange={(e) => setWebhookInput(e.target.value)}
                placeholder={webhookConfigured ? "Saved - paste a new URL to replace it" : "https://discord.com/api/webhooks/..."}
                autoComplete="off"
              />
            </label>
            {webhookError && <p className="error">{webhookError}</p>}
            {webhookSaved && <p className="success">{webhookSaved}</p>}
            <div className="form-row">
              <button type="submit" disabled={savingWebhook || !webhookInput.trim()}>
                {savingWebhook ? "Saving..." : webhookConfigured ? "Replace" : "Save"}
              </button>
              {webhookConfigured && (
                <>
                  <button type="button" onClick={handleTestWebhook} disabled={savingWebhook}>
                    Send test
                  </button>
                  <button
                    type="button"
                    onClick={async () => {
                      setSavingWebhook(true);
                      try {
                        await api.setWebhook("");
                        setWebhookConfigured(false);
                        setWebhookService(null);
                        setWebhookSaved("Notifications off.");
                      } finally {
                        setSavingWebhook(false);
                      }
                    }}
                    disabled={savingWebhook}
                  >
                    Turn off
                  </button>
                </>
              )}
            </div>
          </form>
          <p className="hint">
            A webhook URL lets anyone who has it post into that channel, so it's stored on this server and never sent
            back to the browser &mdash; same as your ESPN session above.
          </p>
        </div>
      )}

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
