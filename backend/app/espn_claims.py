"""Genuine pending ESPN transactions — the waiver claims, free-agent adds
and trade offers a user has actually submitted in ESPN but that haven't
been processed yet.

ESPN treats this as private data and scopes it to the session making the
request, so it only works when the requesting user has saved their own
espn_s2/SWID cookies (see User.espn_s2 in models.py). Without them this
returns "not connected" rather than falling back to the instance-wide
operator cookies, which would show one person's moves to everybody.

Read-only: this reports what ESPN already has. Submitting or cancelling a
claim still happens in ESPN itself.

Everything here is best-effort — ESPN's fantasy API is undocumented and
its payload shapes drift between seasons, so an unrecognised response
yields an empty claim list with a human-readable reason attached, never an
exception that would take the Waivers tab down with it.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.espn_client import ESPNClient, ESPNClientError
from app.espn_constants import position_from_id
from app.models import League, Player, User

logger = logging.getLogger(__name__)

# ESPN's transaction `type` values, mapped to something worth showing a
# human. Anything not listed is passed through as-is rather than dropped —
# a type we haven't seen is still a real pending move.
TYPE_LABELS = {
    "WAIVER": "Waiver claim",
    "WAIVER_ERROR": "Waiver claim",
    "FREEAGENT": "Free agent add",
    "ROSTER": "Roster move",
    "TRADE_PROPOSAL": "Trade offer",
    "TRADE_ACCEPT": "Trade offer",
    "TRADE_UPHOLD": "Trade offer",
    "TRADE": "Trade offer",
}

# Statuses that mean the move is already resolved. Anything *not* in here
# is treated as still pending, including a status we've never seen — an
# undocumented API earns the benefit of the doubt on "is this live?", but
# never on "is this already done?", since showing a processed move as
# pending is the one wrong answer someone might act on.
FINISHED_STATUSES = {
    "EXECUTED",
    "CANCELED",
    "CANCELLED",
    "FAILED",
    "DECLINED",
    "REJECTED",
    "EXPIRED",
    "VETOED",
    "PROCESSED",
}

# A claim list longer than this is a sign we've misread the payload (or
# that the account has every claim it ever made returned as pending), and
# either way it isn't something to render into a panel.
MAX_CLAIMS = 50


def _label_for(txn_type: str) -> str:
    if txn_type in TYPE_LABELS:
        return TYPE_LABELS[txn_type]
    return txn_type.replace("_", " ").title() if txn_type else "Pending move"


def _proposed_at(raw: Any) -> str | None:
    """ESPN timestamps are epoch milliseconds. Returned as an ISO string so
    the caller doesn't have to know that."""
    try:
        return datetime.datetime.utcfromtimestamp(int(raw) / 1000).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _transaction_list(data: dict) -> list[dict]:
    """The pending transactions out of a league payload, whichever key
    this season's API happens to put them under."""
    for key in ("pendingTransactions", "transactions"):
        value = data.get(key)
        if isinstance(value, list):
            return [t for t in value if isinstance(t, dict)]
    return []


def _involves_team(txn: dict, my_team_id: int) -> bool:
    """ESPN already scopes pending claims to the requesting account, but a
    proposed trade is visible to both sides and an account can own more
    than one team across a league's history — so confirm the transaction
    actually touches the team this league is set up for."""
    if txn.get("teamId") == my_team_id:
        return True
    for item in txn.get("items") or []:
        if not isinstance(item, dict):
            continue
        if item.get("toTeamId") == my_team_id or item.get("fromTeamId") == my_team_id:
            return True
    return False


def _parse_items(txn: dict, my_team_id: int) -> tuple[list[int], list[int]]:
    """(player ids coming to my team, player ids leaving it).

    Read off which side of the move my team is on rather than trusting the
    item's own ADD/DROP label: in a trade both sides are "ADD"s from the
    proposing team's point of view, and a claim's drop is the half that
    matters most to whoever is reading this.
    """
    adds: list[int] = []
    drops: list[int] = []
    for item in txn.get("items") or []:
        if not isinstance(item, dict):
            continue
        player_id = item.get("playerId")
        if not isinstance(player_id, int):
            continue
        item_type = (item.get("type") or "").upper()
        if item_type == "LINEUP":
            continue  # a slot change bundled into the move, not an add or drop
        if item.get("toTeamId") == my_team_id:
            adds.append(player_id)
        elif item.get("fromTeamId") == my_team_id:
            drops.append(player_id)
        elif item_type == "ADD":
            adds.append(player_id)
        elif item_type == "DROP":
            drops.append(player_id)
    return adds, drops


def parse_pending_claims(data: dict, my_team_id: int) -> list[dict]:
    """Normalise ESPN's pending-transaction payload into rows the UI can
    render. Player ids only — names are resolved separately (see
    _resolve_names), since they aren't in this payload."""
    claims = []
    for txn in _transaction_list(data):
        # `isPending` is the explicit flag when present; some payloads only
        # carry `status`. Absent both, a transaction that came back from a
        # *pending* view is taken at its word.
        if txn.get("isPending") is False:
            continue
        if (txn.get("status") or "").upper() in FINISHED_STATUSES:
            continue
        if not _involves_team(txn, my_team_id):
            continue

        adds, drops = _parse_items(txn, my_team_id)
        if not adds and not drops:
            continue

        txn_type = (txn.get("type") or "").upper()
        bid = txn.get("bidAmount")
        claims.append(
            {
                "id": str(txn.get("id") or f"{txn_type}-{adds}-{drops}"),
                "type": txn_type,
                "label": _label_for(txn_type),
                # Only waivers carry a meaningful bid; ESPN reports 0 for
                # everything else, which would read as "I bid nothing".
                "bid_amount": bid if isinstance(bid, (int, float)) and txn_type.startswith("WAIVER") else None,
                "scoring_period_id": txn.get("scoringPeriodId"),
                "proposed_at": _proposed_at(txn.get("proposedDate")),
                "add_player_ids": adds,
                "drop_player_ids": drops,
            }
        )
        if len(claims) >= MAX_CLAIMS:
            break

    # Soonest-processing first, then biggest bid — the order someone
    # reviewing their claim list before waivers run would want.
    claims.sort(key=lambda c: (c["scoring_period_id"] or 0, -(c["bid_amount"] or 0)))
    return claims


def _resolve_names(db: Session, league: League, client: ESPNClient, claims: list[dict]) -> dict[int, dict]:
    """{espn_player_id: {"name", "position"}} for every player in `claims`.

    The synced player pool covers rosters plus the top ~200 free agents, so
    it answers most of this for free; only the leftovers cost an extra ESPN
    call, and failing that call just leaves those players showing as ids.
    """
    wanted = {pid for c in claims for pid in (*c["add_player_ids"], *c["drop_player_ids"])}
    if not wanted:
        return {}

    resolved: dict[int, dict] = {}
    rows = (
        db.query(Player.espn_player_id, Player.full_name, Player.position)
        .filter(Player.league_id == league.id, Player.espn_player_id.in_(wanted))
        .all()
    )
    for espn_player_id, full_name, position in rows:
        resolved[espn_player_id] = {"name": full_name, "position": position}

    missing = sorted(wanted - set(resolved))
    if missing:
        try:
            for entry in client.get_players_by_id(missing):
                player_json = entry.get("player", entry) if isinstance(entry, dict) else {}
                pid = player_json.get("id")
                if not isinstance(pid, int):
                    continue
                position_id = player_json.get("defaultPositionId")
                resolved[pid] = {
                    "name": player_json.get("fullName") or f"Player {pid}",
                    "position": position_from_id(position_id) if isinstance(position_id, int) else "",
                }
        except (ESPNClientError, ValueError, TypeError, KeyError, AttributeError):
            logger.info("Could not resolve %d pending-claim player names from ESPN", len(missing))

    return resolved


def _as_players(player_ids: list[int], names: dict[int, dict]) -> list[dict]:
    return [
        {
            "espn_player_id": pid,
            "name": names.get(pid, {}).get("name") or f"Player {pid}",
            "position": names.get(pid, {}).get("position") or "",
        }
        for pid in player_ids
    ]


def get_pending_claims(db: Session, league: League, user: User) -> dict:
    """Everything the Waivers tab needs to show real ESPN claims:

        {"connected": bool, "claims": [...], "error": str | None}

    `connected` is False when this user hasn't saved their ESPN cookies —
    that's the normal, non-error state for a fresh account, and the UI says
    so rather than showing a failure.
    """
    if not (user.espn_s2 and user.espn_swid):
        return {"connected": False, "claims": [], "error": None}

    if league.my_team_id is None:
        return {
            "connected": True,
            "claims": [],
            "error": "Pick which team is yours in Settings first — claims are per-team.",
        }

    client = ESPNClient(
        league_id=league.espn_league_id,
        season=league.season,
        espn_s2=user.espn_s2,
        espn_swid=user.espn_swid,
    )
    try:
        data = client.get_pending_transactions()
    except ESPNClientError as exc:
        # Overwhelmingly this is an expired cookie, which is worth saying
        # plainly — the fix is re-pasting it, not waiting.
        logger.info("Pending-claim fetch failed for league %s: %s", league.id, exc)
        return {
            "connected": True,
            "claims": [],
            "error": (
                "ESPN wouldn't return your pending moves. ESPN sessions expire every few weeks — "
                "re-copy your espn_s2 and SWID cookies in Settings and try again."
                if "401" in str(exc)
                else str(exc)
            ),
        }

    try:
        claims = parse_pending_claims(data, league.my_team_id)
        names = _resolve_names(db, league, client, claims)
        for claim in claims:
            claim["adds"] = _as_players(claim.pop("add_player_ids"), names)
            claim["drops"] = _as_players(claim.pop("drop_player_ids"), names)
    except Exception:  # noqa: BLE001 — an undocumented payload must not 500 the tab
        logger.exception("Could not parse ESPN pending transactions for league %s", league.id)
        return {
            "connected": True,
            "claims": [],
            "error": "ESPN returned pending moves in a format this app didn't recognise.",
        }

    return {"connected": True, "claims": claims, "error": None}
