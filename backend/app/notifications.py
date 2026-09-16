"""Outbound notifications to a Discord or Slack webhook.

The app can only help you if you open it, and the moments that matter
most are the ones where you won't: a Saturday-night injury that breaks
your lineup, waivers processing overnight, kickoff approaching with a
player marked OUT still in a starting slot. This pushes those to you.

Webhooks rather than email on purpose — no mail server, no deliverability
problem, no credentials beyond a URL the user pastes in, and both Discord
and Slack accept the same payload if you send both of their field names.

SECURITY: this is the one place the server makes an HTTP request to a
URL a user supplies, which is a classic server-side request forgery
vector — a URL pointing at 127.0.0.1, or a cloud metadata endpoint, would
have the server fetch it from inside the network and, worse, could be
used to probe what else is reachable. The host allowlist below is the
defense: only the two services this feature exists for, over HTTPS, and
nothing else. Widen it only with that in mind.
"""

from __future__ import annotations

import hashlib
import json
import logging
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# Exact hosts, not suffixes: "discord.com.evil.test" must not match.
ALLOWED_WEBHOOK_HOSTS = {
    "discord.com",
    "discordapp.com",
    "hooks.slack.com",
}

MAX_WEBHOOK_URL_LENGTH = 400
# Discord rejects messages over 2000 characters outright.
MAX_MESSAGE_CHARS = 1900
WEBHOOK_TIMEOUT_SECONDS = 10.0


def webhook_url_error(url: str) -> str | None:
    """None if this URL is safe to POST to, else why it isn't.

    Deliberately strict and deliberately explicit: a vague "invalid URL"
    would have people retrying a URL that can never work.
    """
    url = (url or "").strip()
    if not url:
        return "Enter a webhook URL."
    if len(url) > MAX_WEBHOOK_URL_LENGTH:
        return "That URL is too long to be a webhook."
    try:
        parsed = urlparse(url)
    except ValueError:
        return "That doesn't parse as a URL."
    if parsed.scheme != "https":
        return "Webhook URLs must be https."
    # netloc rather than hostname so a userinfo or port trick
    # ("discord.com@evil.test", "evil.test:443#discord.com") can't slip
    # past a comparison that only looks at part of the authority.
    if parsed.username or parsed.password or parsed.port:
        return "Webhook URLs can't carry credentials or a port."
    if (parsed.hostname or "").lower() not in ALLOWED_WEBHOOK_HOSTS:
        return "Only Discord and Slack webhook URLs are supported."
    if not parsed.path or parsed.path == "/":
        return "That looks like a bare domain, not a webhook URL."
    return None


def send_webhook(url: str, message: str) -> bool:
    """Post one message. Best-effort: never raises, returns whether it
    landed, and re-validates the URL because a stored value could predate
    a tightening of the rules above."""
    if webhook_url_error(url):
        return False
    body = message[:MAX_MESSAGE_CHARS]
    # Discord reads "content", Slack reads "text", and each ignores the
    # other's field — so one payload serves both with no configuration.
    payload = {"content": body, "text": body}
    try:
        with httpx.Client(timeout=WEBHOOK_TIMEOUT_SECONDS) as client:
            resp = client.post(url, json=payload)
        # 2xx is success; Discord returns 204 with no body.
        if 200 <= resp.status_code < 300:
            return True
        logger.info("Webhook rejected the message: HTTP %s", resp.status_code)
        return False
    except httpx.HTTPError as exc:
        logger.info("Webhook delivery failed: %s", exc)
        return False


def fingerprint(payload: object) -> str:
    """A stable hash of what a notification is about, so the same problem
    isn't re-sent every time the scheduler wakes up. Changes only when the
    underlying situation does."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _line_for_alert(alert: dict) -> str:
    player = alert["player"]
    where = player["slot"] if player["is_starter"] else "bench"
    reason = alert["reason"].title() if alert["reason"] != "on bye" else "on bye"
    line = f"- **{player['name']}** ({player['position']}, {where}) — {reason}"
    replacements = alert.get("replacements") or []
    if player["is_starter"] and replacements:
        line += f". Free agent: {replacements[0]['name']}"
    return line


def build_alert_message(league_name: str, week: int, alerts: list[dict]) -> str | None:
    """A lineup-problem message, or None when nothing needs a decision.

    Only starters make it in. A hurt bench player is information, not a
    problem, and a notification that isn't actionable teaches people to
    ignore the next one.
    """
    starters = [a for a in alerts if a["player"]["is_starter"]]
    if not starters:
        return None
    lines = [f"**{league_name}** — Week {week} lineup check", ""]
    lines += [_line_for_alert(a) for a in starters]
    lines.append("")
    lines.append(f"{len(starters)} starter{'s' if len(starters) != 1 else ''} needs attention.")
    return "\n".join(lines)


def build_changes_message(league_name: str, changes: dict) -> str | None:
    """What moved in the league since the last sync — the digest half."""
    items = (changes or {}).get("items") or []
    if not items:
        return None
    lines = [f"**{league_name}** — what changed since your last sync", ""]
    for item in items[:12]:
        name = item.get("name")
        if not name:
            continue
        detail = item.get("detail")
        lines.append(f"- **{name}** — {detail}" if detail else f"- **{name}**")
    if len(items) > 12:
        lines.append(f"- ...and {len(items) - 12} more")
    return "\n".join(lines)


def notify_league(db, user, league) -> list[str]:
    """Send whatever this league currently warrants to this user, and
    record it so it isn't sent again. Returns the kinds actually sent.

    Called from the background scheduler, so it swallows everything: one
    account's bad webhook must not stop anyone else's notifications, let
    alone the sync loop the scheduler shares.
    """
    from app.alerts import get_roster_alerts  # imported here to avoid a cycle

    if not user.webhook_url or league.my_team_id is None:
        return []

    already = dict(league.notified or {})
    sent = []

    try:
        alerts = get_roster_alerts(db, league.id, league.my_team_id)
        starters = [a for a in (alerts.get("alerts") or []) if a["player"]["is_starter"]]
        # Fingerprint the situation, not the rendered text: a reworded
        # message shouldn't re-notify, and a genuinely new injury should.
        alert_key = fingerprint([
            (a["player"]["espn_player_id"], a["reason"]) for a in starters
        ]) if starters else ""
        if alert_key and already.get("alerts") != alert_key:
            message = build_alert_message(league.name, alerts.get("week") or 0, alerts.get("alerts") or [])
            if message and send_webhook(user.webhook_url, message):
                already["alerts"] = alert_key
                sent.append("alerts")
        elif not alert_key and already.get("alerts"):
            # Everything cleared up; forget it so the next problem notifies.
            already.pop("alerts", None)
    except Exception:  # noqa: BLE001 — see docstring
        logger.exception("Could not build alert notification for league %s", league.id)

    try:
        changes = league.sync_changes or {}
        change_key = fingerprint(changes.get("at")) if changes.get("items") else ""
        if change_key and already.get("changes") != change_key:
            message = build_changes_message(league.name, changes)
            if message and send_webhook(user.webhook_url, message):
                already["changes"] = change_key
                sent.append("changes")
    except Exception:  # noqa: BLE001
        logger.exception("Could not build change notification for league %s", league.id)

    if already != (league.notified or {}):
        league.notified = already
        db.commit()
    return sent


def run_due_notifications() -> int:
    """One pass over every league whose owner has notifications on.

    Cheap by design: it reads already-synced data, so it can run on the
    scheduler's short interval without touching ESPN at all.
    """
    from app.db import SessionLocal
    from app.models import League, User

    delivered = 0
    db = SessionLocal()
    try:
        pairs = (
            db.query(League, User)
            .join(User, League.user_id == User.id)
            .filter(User.webhook_url.isnot(None))
            .all()
        )
        for league, user in pairs:
            try:
                delivered += len(notify_league(db, user, league))
            except Exception:  # noqa: BLE001 — one account can't break the pass
                db.rollback()
                logger.exception("Notification pass failed for league %s", league.id)
    finally:
        db.close()
    return delivered
