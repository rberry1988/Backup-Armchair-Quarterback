#!/usr/bin/env python3
"""Sign in with ChatGPT, on your own machine, and print a token to paste in.

Run this where your browser is — your laptop, not the server.

The app hands you the whole command. In Backup Armchair Quarterback go to
Settings -> Account -> AI analyst, click "Sign in with ChatGPT", and copy
what it shows:

    python3 chatgpt_signin.py --connect bacq-pair-1....

That opens ChatGPT's sign-in page, waits for you to approve, and delivers
the result straight back to the app — nothing to copy afterwards. From then
on the app's analyses come out of your ChatGPT Plus/Pro allowance instead of
API credits.

Run it with no arguments and it prints the credential instead, for pasting
in by hand. Same result, one more step.

Why this is a separate script and not a button in the app: OpenAI's
sign-in flow for open-source apps only accepts a redirect back to
http://127.0.0.1 — your own machine. A server that other people reach over
the network has no such address to be sent back to. So the sign-in happens
here, locally, and only the resulting token travels.

Standard library only, on purpose: this runs on whatever machine you happen
to be at, and asking you to pip install something first would be a worse
experience than the problem it solves.

Requires Python 3.9+. You can revoke this app at any time from
ChatGPT -> Settings -> Connected apps.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import json
import os
import pathlib
import secrets
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser

AUTHORIZE_URL = "https://auth.openai.com/api/accounts/authorize"
TOKEN_URL = "https://auth.openai.com/api/accounts/oauth/token"
RESOURCE = "https://api.openai.com/v1"

# resource.invoke + chatgpt.tokens.use.direct are what actually authorise
# spending the plan; openid/profile/email identify the account and
# offline_access is what makes a refresh token come back at all. Drop any one
# of them and the sign-in still "works" while the app can't use it.
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
PLAN_USAGE_SCOPE = "chatgpt.tokens.use.direct"

APP_NAME = "Backup Armchair Quarterback"
BLOB_PREFIX = "bacq-chatgpt-1."
# Matches chatgpt_oauth.CONNECT_PREFIX on the server.
CONNECT_PREFIX = "bacq-pair-1."

# The port OpenAI's docs use in their example. Any loopback port works as
# long as the authorize request and the token exchange agree on it, but
# sticking to the documented one avoids surprises with allowlists.
PREFERRED_PORT = 1455

# Where the issued client id is remembered between runs. Re-registering on
# every sign-in would litter the account's connected-apps list with a new
# entry each time; reusing it means a second run shows up as the same app.
STATE_DIR = pathlib.Path(
    os.environ.get("XDG_CONFIG_HOME") or (pathlib.Path.home() / ".config")
) / "backup-armchair-quarterback"
STATE_FILE = STATE_DIR / "chatgpt-client.json"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _load_client_id() -> str | None:
    try:
        return json.loads(STATE_FILE.read_text()).get("client_id") or None
    except (OSError, ValueError):
        return None


def _save_client_id(client_id: str) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps({"client_id": client_id}, indent=2))
        STATE_FILE.chmod(0o600)
    except OSError:
        # Only an optimisation. A failure here costs a duplicate entry in the
        # connected-apps list next time, which isn't worth failing over.
        pass


def _host_id() -> str:
    """A stable per-machine id, which the authorize request requires to be
    distinct per host. Derived rather than random so re-running on the same
    machine reads as the same host."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"bacq-{uuid.getnode()}-{socket.gethostname()}"))


def _account_email(id_token: str) -> str | None:
    """Pull the email out of the ID token, for a human-readable label only.

    Not verified, and deliberately not trusted for anything: the token's
    value to this app is as a bearer credential, and the email is a string
    shown back so you can tell which ChatGPT account you connected.
    """
    try:
        payload = id_token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return claims.get("email")
    except (IndexError, ValueError, UnicodeDecodeError):
        return None


def _parse_connect(value: str) -> dict:
    """Decode the connect string the app showed. Mirrors
    chatgpt_oauth.make_connect_string() on the server side."""
    text = "".join((value or "").split())
    if not text.startswith(CONNECT_PREFIX):
        raise ValueError(
            "That doesn't look like a connect string. Copy the whole command the app showed, "
            f"including the part starting with \u201c{CONNECT_PREFIX}\u201d."
        )
    encoded = text[len(CONNECT_PREFIX):]
    try:
        data = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        return {"url": str(data["url"]), "token": str(data["token"])}
    except Exception as exc:  # noqa: BLE001 - any decode failure means the same thing
        raise ValueError("That connect string is damaged — copy the whole command again.") from exc


def _confirm_destination(url: str) -> bool:
    """A ChatGPT credential is about to cross the network to this app.

    Over https that's fine. Over plain http on a home network it's readable
    by anything on the wire, which is a worse trade than it is for an
    ordinary app login — so it's the user's call, made explicitly, rather
    than something that quietly happens.
    """
    parsed = urllib.parse.urlparse(url)
    local = parsed.hostname in ("127.0.0.1", "localhost", "::1")
    if parsed.scheme == "https" or local:
        return True
    print(f"\n  WARNING: {url} is plain http, not https.")
    print("  Your ChatGPT credential would cross the network unencrypted.")
    try:
        return input("  Continue anyway? [y/N] ").strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def _deliver(target: dict, blob: str) -> bool:
    """Hand the credential to the app, authenticating with the pairing token."""
    body = json.dumps({"pair_token": target["token"], "chatgpt_token": blob}).encode()
    request = urllib.request.Request(
        f"{target['url']}/api/auth/ai-pairing/claim",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            json.loads(response.read())
        return True
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = json.loads(exc.read()).get("detail", "")
        except Exception:  # noqa: BLE001 - a non-JSON error body is still an error
            pass
        print(f"\nThe app rejected the sign-in ({exc.code}): {detail or 'no reason given'}",
              file=sys.stderr)
    except urllib.error.URLError as exc:
        print(f"\nCouldn't reach the app at {target['url']}: {exc.reason}", file=sys.stderr)
    return False


class _Callback(http.server.BaseHTTPRequestHandler):
    """Catches the one redirect back from the browser, then stops."""

    result: dict = {}
    done = threading.Event()

    def do_GET(self):  # noqa: N802  (http.server's required spelling)
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/auth/callback":
            self.send_error(404)
            return
        _Callback.result = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        ok = "code" in _Callback.result and "error" not in _Callback.result
        body = (
            "<h2>Signed in.</h2><p>Close this tab and go back to the terminal.</p>"
            if ok
            else "<h2>Sign-in was declined.</h2><p>Nothing was saved. You can close this tab.</p>"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        _Callback.done.set()

    def log_message(self, *_args):
        pass  # the default logs every request to stderr, which is just noise here


def _serve(port: int) -> http.server.HTTPServer:
    # 127.0.0.1 specifically, not localhost and not 0.0.0.0: the docs require
    # the literal loopback address, and binding wider would expose the
    # callback to the network for as long as this runs.
    server = http.server.HTTPServer(("127.0.0.1", port), _Callback)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _post_form(url: str, fields: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(fields).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:400]
        raise SystemExit(f"\nOpenAI rejected the token exchange ({exc.code}):\n  {detail}\n")
    except urllib.error.URLError as exc:
        raise SystemExit(f"\nCouldn't reach OpenAI: {exc.reason}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--connect",
        metavar="CONNECT_STRING",
        help="deliver the sign-in straight to the app (the string it showed you)",
    )
    parser.add_argument("--port", type=int, default=PREFERRED_PORT, help=f"loopback port (default {PREFERRED_PORT})")
    parser.add_argument("--no-browser", action="store_true", help="print the URL instead of opening it")
    parser.add_argument("--timeout", type=int, default=300, help="seconds to wait for sign-in (default 300)")
    args = parser.parse_args()

    target = None
    if args.connect:
        # Parsed before the browser is opened: a mangled copy should fail in
        # a second, not after a round trip through ChatGPT.
        try:
            target = _parse_connect(args.connect)
        except ValueError as exc:
            print(f"\n{exc}\n", file=sys.stderr)
            return 1
        if not _confirm_destination(target["url"]):
            return 1

    try:
        server = _serve(args.port)
    except OSError:
        # Something already has 1455. An ephemeral port is fine -- the only
        # requirement is that authorize and exchange use the same one.
        server = _serve(0)
    port = server.server_address[1]
    redirect_uri = f"http://127.0.0.1:{port}/auth/callback"

    verifier = _b64url(secrets.token_bytes(64))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)

    saved_client_id = _load_client_id()
    params = {
        # dynamic_agent_client is the first-time registration entrypoint, not
        # a client id to keep; the real one comes back on the callback. A
        # later run passes the issued id instead and re-authorises it.
        "client_id": saved_client_id or "dynamic_agent_client",
        "ext_agent_host_id": _host_id(),
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": SCOPES,
        "resource": RESOURCE,
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if not saved_client_id:
        # Only sent on first registration -- it's what names the app in your
        # ChatGPT connected-apps list.
        params["agent_name_hint"] = APP_NAME

    url = f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"

    print(f"\n{APP_NAME} — Sign in with ChatGPT")
    print("=" * 60)
    if args.no_browser or not webbrowser.open(url):
        print("\nOpen this in your browser:\n")
        print(url)
    else:
        print("\nA browser window should have opened. Approve the request there.")
    print(f"\nWaiting up to {args.timeout}s on {redirect_uri} ...")

    if not _Callback.done.wait(timeout=args.timeout):
        server.shutdown()
        print("\nTimed out waiting for sign-in. Nothing was saved.", file=sys.stderr)
        return 1
    server.shutdown()

    result = _Callback.result
    if result.get("error"):
        print(f"\nSign-in declined ({result['error']}). Nothing was saved.", file=sys.stderr)
        return 1
    if not secrets.compare_digest(result.get("state", ""), state):
        # A mismatch means this callback didn't come from the request we
        # made, so the code it carries isn't ours to exchange.
        print("\nSecurity check failed (state mismatch). Nothing was saved.", file=sys.stderr)
        return 1

    client_id = result.get("client_id") or saved_client_id
    if not client_id:
        print("\nOpenAI didn't return a client id. Try again.", file=sys.stderr)
        return 1
    if saved_client_id and result.get("client_id") and result["client_id"] != saved_client_id:
        print("\nOpenAI returned a different client id than the one requested. Stopping.", file=sys.stderr)
        return 1

    tokens = _post_form(
        TOKEN_URL,
        {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": result["code"],
            "code_verifier": verifier,
            "redirect_uri": redirect_uri,
            "resource": RESOURCE,
        },
    )

    granted = tokens.get("scope", "")
    if PLAN_USAGE_SCOPE not in granted.split():
        print(
            "\nSigned in, but ChatGPT plan usage wasn't granted, so the app still couldn't "
            "run anything on your plan.\nRun this again and approve the plan-usage request.",
            file=sys.stderr,
        )
        return 1
    if not tokens.get("refresh_token"):
        print(
            "\nNo refresh token came back, so the app couldn't keep the sign-in alive past an "
            "hour.\nRun this again and make sure you approve offline access.",
            file=sys.stderr,
        )
        return 1

    _save_client_id(client_id)

    blob = BLOB_PREFIX + _b64url(
        json.dumps(
            {
                "client_id": client_id,
                "access_token": tokens["access_token"],
                "refresh_token": tokens["refresh_token"],
                "expires_at": time.time() + float(tokens.get("expires_in") or 3600),
                "account_email": _account_email(tokens.get("id_token", "")),
                "scopes": granted,
            },
            separators=(",", ":"),
        ).encode()
    )

    email = _account_email(tokens.get("id_token", ""))
    print("\n" + "=" * 60)
    print(f"Signed in{f' as {email}' if email else ''}.")

    if target:
        print(f"\nHanding it to the app at {target['url']} ...")
        if not _deliver(target, blob):
            # Not a dead end: the sign-in itself worked, only the delivery
            # failed, so offer the manual path rather than making them do
            # the whole thing again.
            print("\nThe sign-in worked, so you can still finish by hand. Copy this ENTIRE line")
            print("into Settings \u2192 Account \u2192 AI analyst, under \u201cpaste a sign-in token by hand\u201d:\n")
            print(blob)
            return 1
        print("Done \u2014 the app is connected. Go back to it; it has already updated itself.")
    else:
        print("\nCopy this ENTIRE line into Settings \u2192 Account \u2192 AI analyst:")
        print("(it's one line, however your terminal wraps it)\n")
        print(blob)

    print("\n" + "=" * 60)
    print(
        "This is a credential for your ChatGPT account \u2014 treat it like a password.\n"
        "Revoke it any time from ChatGPT \u2192 Settings \u2192 Connected apps.\n"
        "It stops working after 30 days without use; re-run this to renew."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
