"""The league's transaction log: who picked up whom, what it cost, and how
each manager spends.

Two things this answers that nothing else in the app could. First, plain
curiosity — the feed every fantasy site has and this one didn't. Second,
and more useful: when the waiver tab suggests a bid, the question that
actually decides it is who else is likely to bid and how they behave. A
manager who has won six claims at an average of $3 is not the same threat
as one who has spent $70 on two.

Fetched during sync rather than per request: the log only changes when a
transaction processes, and a stored copy keeps the feed instant and works
even when ESPN is unreachable. Best-effort throughout — an unparseable
payload yields an empty feed, never an exception that would fail the sync
around it.
"""

from __future__ import annotations

import datetime
import logging
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)

# Enough to see the season's shape without turning a League row into a
# transaction archive. Newest first, so this keeps the recent end.
MAX_STORED_TRANSACTIONS = 150

TYPE_LABELS = {
    "WAIVER": "Waiver claim",
    "FREEAGENT": "Free agent add",
    "ROSTER": "Roster move",
    "TRADE_ACCEPT": "Trade",
    "TRADE_UPHOLD": "Trade",
    "TRADE": "Trade",
    "DRAFT": "Draft pick",
}

# A transaction that never completed says nothing about how a manager
# behaves, and showing a failed claim as though it happened is worse than
# omitting it.
COMPLETED_STATUSES = {"EXECUTED", "PROCESSED", "SUCCEEDED", ""}


def _label_for(txn_type: str) -> str:
    if txn_type in TYPE_LABELS:
        return TYPE_LABELS[txn_type]
    return txn_type.replace("_", " ").title() if txn_type else "Transaction"


def _executed_at(raw: Any) -> str | None:
    try:
        return datetime.datetime.utcfromtimestamp(int(raw) / 1000).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _transaction_list(data: dict) -> list[dict]:
    for key in ("transactions", "communications"):
        value = data.get(key)
        if isinstance(value, list):
            return [t for t in value if isinstance(t, dict)]
    return []


def parse_transactions(data: dict, limit: int = MAX_STORED_TRANSACTIONS) -> list[dict]:
    """ESPN's transaction log, normalised and newest first.

    Adds and drops are recorded from the transacting team's point of view,
    which for a trade means each side's outgoing players show as drops.
    Player ids only — names are resolved by the caller, which has the
    league's own history to draw on.
    """
    rows = []
    for txn in _transaction_list(data):
        status = (txn.get("status") or "").upper()
        if status not in COMPLETED_STATUSES:
            continue
        # Pending claims are a separate feature (app/espn_claims.py); this
        # is the record of what already happened.
        if txn.get("isPending") is True:
            continue

        team_id = txn.get("teamId")
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
                continue
            # Direction first, and without deferring to the item's own
            # label: in a trade every item is typed ADD from the proposing
            # side's framing, so trusting the label would file a player
            # this team gave away as one it acquired. The label is only the
            # fallback for a payload that omits the team ids.
            if item.get("toTeamId") == team_id:
                adds.append(player_id)
            elif item.get("fromTeamId") == team_id:
                drops.append(player_id)
            elif item_type == "ADD":
                adds.append(player_id)
            elif item_type == "DROP":
                drops.append(player_id)

        if not adds and not drops:
            continue

        txn_type = (txn.get("type") or "").upper()
        bid = txn.get("bidAmount")
        rows.append(
            {
                "id": str(txn.get("id") or f"{txn_type}-{team_id}-{adds}-{drops}"),
                "type": txn_type,
                "label": _label_for(txn_type),
                "team_id": team_id,
                # Only a waiver claim has a bid; ESPN reports 0 elsewhere,
                # which would read as "they bid nothing" rather than "no bid
                # was involved".
                "bid_amount": bid if isinstance(bid, (int, float)) and txn_type.startswith("WAIVER") else None,
                "scoring_period_id": txn.get("scoringPeriodId"),
                "executed_at": _executed_at(txn.get("processDate") or txn.get("proposedDate")),
                "add_player_ids": adds,
                "drop_player_ids": drops,
            }
        )

    rows.sort(key=lambda r: (r["scoring_period_id"] or 0, r["executed_at"] or ""), reverse=True)
    return rows[:limit]


def summarize_spending(transactions: list[dict]) -> dict[int, dict]:
    """{team_id: {spent, claims, biggest_bid, average_bid}} across the
    waiver claims in `transactions`.

    This is the part that feeds bid advice: what a manager has actually
    been willing to pay tells you far more about the next auction than
    their remaining balance alone.
    """
    spent: dict[int, float] = defaultdict(float)
    bids: dict[int, list[float]] = defaultdict(list)
    moves: dict[int, int] = defaultdict(int)

    for txn in transactions:
        team_id = txn.get("team_id")
        if not isinstance(team_id, int):
            continue
        moves[team_id] += 1
        bid = txn.get("bid_amount")
        if isinstance(bid, (int, float)) and bid > 0:
            spent[team_id] += bid
            bids[team_id].append(float(bid))

    summary = {}
    for team_id in set(moves) | set(spent):
        team_bids = bids.get(team_id, [])
        summary[team_id] = {
            "spent": round(spent.get(team_id, 0.0)),
            "moves": moves.get(team_id, 0),
            "winning_claims": len(team_bids),
            "biggest_bid": round(max(team_bids)) if team_bids else 0,
            "average_bid": round(sum(team_bids) / len(team_bids), 1) if team_bids else 0.0,
        }
    return summary


def build_activity(transactions: list[dict], team_names: dict[int, str], player_names: dict[int, str]) -> dict:
    """Turn parsed rows into the stored feed: names attached, ids gone.

    Stored resolved rather than resolved on read because the names come
    from this league's own history, which a later sync can wipe — a player
    dropped in week 2 and never re-rostered would otherwise become a bare
    id the moment he left the pool.
    """
    def named(ids: list[int]) -> list[dict]:
        return [{"espn_player_id": pid, "name": player_names.get(pid) or f"Player {pid}"} for pid in ids]

    feed = []
    for txn in transactions:
        feed.append(
            {
                **{k: v for k, v in txn.items() if k not in ("add_player_ids", "drop_player_ids")},
                "team": team_names.get(txn.get("team_id")) or "Unknown team",
                "adds": named(txn["add_player_ids"]),
                "drops": named(txn["drop_player_ids"]),
            }
        )

    spending = summarize_spending(transactions)
    return {
        "transactions": feed,
        "spending": [
            {"team_id": tid, "team": team_names.get(tid) or "Unknown team", **stats}
            for tid, stats in sorted(spending.items(), key=lambda kv: -kv[1]["spent"])
        ],
    }
