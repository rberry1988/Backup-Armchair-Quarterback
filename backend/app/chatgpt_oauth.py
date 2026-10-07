"""Paying for OpenAI calls with a ChatGPT Plus/Pro plan instead of an API key.

OpenAI's "Sign in with ChatGPT" lets a subscriber spend their plan allowance
inside a third-party app. The sanctioned open-source flow is an OAuth
authorization-code exchange with PKCE — but its redirect URI has to be an
HTTP loopback on 127.0.0.1, which is a flow designed for something running
on the same machine as the browser. This app is a server other people reach
over the network, so there is no loopback for it to redirect to.

So the dance happens on the user's own machine: tools/chatgpt_signin.py runs
the loopback flow locally and prints one opaque blob, which they paste into
Settings -> Account the same way they'd paste an API key. From there the
server owns the credential: it refreshes the access token as it expires and
spends the plan on their behalf.

Worth being clear-eyed about the tradeoff, since it's different from an API
key. What's stored here is tied to a ChatGPT *account*, not a metered API
key that can be revoked in isolation — so it never leaves the server, the
same rule the ESPN cookies and the webhook URL live under. Users can see and
revoke this app from their ChatGPT settings at any time, and that's the
honest answer to "how do I take it back".

Two things about OpenAI's tokens shape this module:

- Access tokens last an hour; refresh tokens last 30 days on a rolling
  window, so an account that goes a month without an analysis has to sign
  in again. Nothing can be done about that but say so clearly.
- **Every refresh rotates the refresh token.** The old one stops working the
  moment the new one is issued, so a refresh that succeeds upstream but
  isn't persisted here locks the account out until they re-run the helper.
  That's why _refresh() commits before the token is used for anything.

Nothing in here raises for a credential problem — callers get AiAdvisorError
subclasses from app.ai_advisor, so a failure arrives as a sentence the user
can act on.
"""

from __future__ import annotations

import base64
import binascii
import datetime
import hashlib
import json
import logging
import secrets

import httpx
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

TOKEN_URL = "https://auth.openai.com/api/accounts/oauth/token"

# The scope that actually authorises spending the plan. The docs are explicit
# that a valid ID token alone does not: without this, sign-in succeeded but
# inference will be refused, and catching that here beats catching it as a
# 401 on someone's first analysis.
PLAN_USAGE_SCOPE = "chatgpt.tokens.use.direct"

# What tools/chatgpt_signin.py prints. Prefixed and versioned so a wrong
# paste (an API key, a URL, half a blob) is identified as such rather than
# failing later as an opaque 401, and so a future format change can be told
# apart from a corrupt one.
BLOB_PREFIX = "bacq-chatgpt-1."

REQUIRED_FIELDS = ("client_id", "access_token", "refresh_token")

# Refresh this far before the hour is actually up. Covers clock skew between
# this box and OpenAI's, plus the time the request itself takes.
EXPIRY_SKEW_SECONDS = 120

REFRESH_TIMEOUT_SECONDS = 30.0


class ChatGptAuthError(Exception):
    """Raised with a message for the user. app.ai_advisor translates these
    into its own error classes so the HTTP layer has one thing to catch."""


def _utcnow() -> datetime.datetime:
    return datetime.datetime.utcnow()


def parse_blob(pasted: str) -> dict:
    """Turn what the helper printed into the bundle we store.

    Deliberately strict: every failure mode here is a person pasting the
    wrong thing, and each gets a different sentence back, because "invalid
    token" sends someone hunting in the wrong place.
    """
    text = "".join((pasted or "").split())  # tolerate newlines from a wrapped terminal
    if not text:
        raise ChatGptAuthError("Nothing pasted.")
    if text.startswith("sk-"):
        raise ChatGptAuthError(
            "That's an API key, not a ChatGPT sign-in. Switch the mode above to "
            "“API key”, or run the sign-in helper to get a token."
        )
    if not text.startswith(BLOB_PREFIX):
        raise ChatGptAuthError(
            "That doesn't look like the sign-in helper's output. Copy the whole line it "
            f"printed, starting with “{BLOB_PREFIX}”."
        )

    encoded = text[len(BLOB_PREFIX):]
    try:
        # urlsafe_b64decode is strict about padding; the helper strips it.
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        data = json.loads(raw)
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise ChatGptAuthError(
            "That token is damaged — it looks like only part of it was copied. Run the "
            "helper again and copy the whole line."
        ) from exc

    if not isinstance(data, dict):
        raise ChatGptAuthError("That token isn't in the expected format. Run the helper again.")

    missing = [f for f in REQUIRED_FIELDS if not data.get(f)]
    if missing:
        raise ChatGptAuthError(
            "That token is missing " + ", ".join(missing) + ". Run the helper again."
        )

    scopes = data.get("scopes") or ""
    if PLAN_USAGE_SCOPE not in scopes.split():
        raise ChatGptAuthError(
            "That sign-in didn't include permission to use your ChatGPT plan. Run the helper "
            "again and approve the plan-usage request — signing in alone isn't enough."
        )

    return {
        "client_id": str(data["client_id"]),
        "access_token": str(data["access_token"]),
        "refresh_token": str(data["refresh_token"]),
        # Treated as already-expired when absent, so the first call refreshes
        # rather than firing a possibly-stale token at the API.
        "expires_at": float(data.get("expires_at") or 0),
        # Display only — shown back as "signed in as ..." so someone with two
        # ChatGPT accounts can tell which one this is. Never used to decide
        # anything.
        "account_email": str(data.get("account_email") or "") or None,
        "scopes": scopes,
    }


def _expired(bundle: dict) -> bool:
    expires_at = bundle.get("expires_at") or 0
    return _utcnow().timestamp() >= (expires_at - EXPIRY_SKEW_SECONDS)


def _refresh(db: Session, user) -> dict:
    """Swap the refresh token for a fresh pair, and persist before returning.

    The commit is the point. OpenAI rotates the refresh token on every
    successful refresh, so the one we just sent is already dead upstream —
    if the new pair doesn't reach the database, this account can't refresh
    again and the user has to re-run the helper for no visible reason.
    """
    bundle = dict(user.ai_oauth or {})
    try:
        response = httpx.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": bundle["refresh_token"],
                "client_id": bundle["client_id"],
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=REFRESH_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        # A network blip isn't a dead credential — say so, and leave what's
        # stored alone so the next attempt can still use it.
        raise ChatGptAuthError(
            "Couldn't reach OpenAI to renew your ChatGPT sign-in. Try again in a moment."
        ) from exc

    if response.status_code != 200:
        # 400/401 here is effectively always invalid_grant: the refresh token
        # expired (30 days unused) or was revoked from ChatGPT settings.
        # Either way it will never work again, so clear it rather than
        # letting every future analysis fail the same way.
        logger.warning("ChatGPT token refresh failed with %s for user %s", response.status_code, user.id)
        user.ai_oauth = None
        db.commit()
        raise ChatGptAuthError(
            "Your ChatGPT sign-in has expired or been revoked. Run the sign-in helper again "
            "and paste the new token in Settings → Account."
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise ChatGptAuthError("OpenAI returned an unreadable response while renewing your sign-in.") from exc

    access_token = payload.get("access_token")
    if not access_token:
        raise ChatGptAuthError("OpenAI didn't return a new token while renewing your sign-in.")

    bundle["access_token"] = access_token
    # Rotation: keep the replacement. Falling back to the old one would store
    # a token we know is dead.
    bundle["refresh_token"] = payload.get("refresh_token") or bundle["refresh_token"]
    bundle["expires_at"] = _utcnow().timestamp() + float(payload.get("expires_in") or 3600)
    if payload.get("scope"):
        bundle["scopes"] = payload["scope"]

    # Reassigned wholesale rather than mutated in place: SQLAlchemy's JSON
    # column doesn't track mutation of the dict it handed us, so an in-place
    # edit would be silently dropped at commit.
    user.ai_oauth = bundle
    db.commit()
    return bundle


def access_token(db: Session, user) -> str:
    """A token that's good right now, refreshing first if it isn't."""
    bundle = user.ai_oauth or {}
    if not bundle.get("access_token") or not bundle.get("refresh_token"):
        raise ChatGptAuthError(
            "No ChatGPT sign-in saved. Run the sign-in helper and paste the token in "
            "Settings → Account."
        )
    if _expired(bundle):
        bundle = _refresh(db, user)
    return bundle["access_token"]


def status(user) -> dict:
    """What the UI may know about this credential. Never the tokens."""
    bundle = user.ai_oauth or {}
    if not bundle.get("access_token"):
        return {"connected": False}
    return {
        "connected": True,
        "account_email": bundle.get("account_email"),
        "expires_at": datetime.datetime.utcfromtimestamp(bundle["expires_at"])
        if bundle.get("expires_at")
        else None,
    }


# ---------------------------------------------------------------------------
# Pairing: getting the helper's result into this account without a copy/paste
# ---------------------------------------------------------------------------
#
# The sign-in has to happen on the user's own machine (see this module's
# docstring), but nothing says *they* have to ferry the result. Pairing lets
# the helper deliver it directly:
#
#   1. They click "Sign in with ChatGPT". The app mints a single-use pairing
#      token and shows one command to copy.
#   2. The helper runs locally, does the OAuth dance, and POSTs the
#      credential back to the app, authenticating with that pairing token.
#   3. The panel, which has been polling, flips to connected.
#
# The pairing token authorises writing an AI credential to one account, so it
# is treated as the bearer credential it is: 256 bits of entropy, only its
# hash stored, single-use, and short-lived. It is never typed by a human —
# it rides inside a command line the UI offers as one click to copy — so
# there's no reason to trade entropy for readability.

PAIRING_TTL_MINUTES = 15

# Prefix + version on the connect string for the same reason the credential
# blob has one: so a stale or wrong paste is named as such.
CONNECT_PREFIX = "bacq-pair-1."


def new_pairing(user) -> str:
    """Mint a pairing token for this account, replacing any pending one.

    Returns the raw token, which the caller shows once and never stores —
    only its hash goes to the database.
    """
    token = secrets.token_urlsafe(32)
    user.ai_pair_hash = hashlib.sha256(token.encode()).hexdigest()
    user.ai_pair_expires_at = _utcnow() + datetime.timedelta(minutes=PAIRING_TTL_MINUTES)
    return token


def make_connect_string(api_base: str, token: str) -> str:
    """One opaque argument carrying both where to deliver and the token.

    A single blob rather than two flags because it is copied by hand into a
    shell: a URL and a token as separate arguments is two chances to lose
    half of it, and one chance to mangle it on quoting.
    """
    payload = json.dumps({"url": api_base.rstrip("/"), "token": token}, separators=(",", ":"))
    return CONNECT_PREFIX + base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def parse_connect_string(value: str) -> dict:
    """The helper's side of make_connect_string(). Raises ChatGptAuthError."""
    text = "".join((value or "").split())
    if not text.startswith(CONNECT_PREFIX):
        raise ChatGptAuthError(
            f"That doesn't look like a connect string. Copy the whole command the app showed, "
            f"including the part starting with “{CONNECT_PREFIX}”."
        )
    encoded = text[len(CONNECT_PREFIX):]
    try:
        data = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        url, token = data["url"], data["token"]
    except (binascii.Error, ValueError, KeyError, UnicodeDecodeError) as exc:
        raise ChatGptAuthError("That connect string is damaged — copy the whole command again.") from exc
    return {"url": str(url), "token": str(token)}


def find_pairing(db: Session, token: str):
    """The account a pairing token belongs to, or None.

    Looked up by hash, so an expired or already-used token simply matches
    nothing — there is no path here that reveals whether a given token ever
    existed, only whether it is usable right now.
    """
    from app.models import User  # local import: models imports this module's siblings

    if not token:
        return None
    digest = hashlib.sha256(token.encode()).hexdigest()
    user = db.query(User).filter(User.ai_pair_hash == digest).first()
    if user is None:
        return None
    if not user.ai_pair_expires_at or user.ai_pair_expires_at < _utcnow():
        # Expired tokens are cleared on sight rather than left to linger as
        # rows that still look like live credentials.
        user.ai_pair_hash = None
        user.ai_pair_expires_at = None
        db.commit()
        return None
    return user


def clear_pairing(user) -> None:
    """Single use: a pairing that has done its job can't do it again."""
    user.ai_pair_hash = None
    user.ai_pair_expires_at = None
