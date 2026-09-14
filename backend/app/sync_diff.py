"""What changed since the last sync.

Rosters and free agents are wiped and rebuilt on every sync, so "what's
different" has to be captured in the same transaction: snapshot the old
state before the wipe, compare against the rebuilt state, and store the
result on the League. That turns an otherwise invisible refresh into the
digest you actually want on a Tuesday morning — who got hurt, who got
picked up, whose ownership is spiking.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Player, RosterEntry, Team

# An ownership move this big in a few days means the league (and the wider
# ESPN player pool) is reacting to something — usually a role change.
OWNERSHIP_JUMP_PCT = 5.0
# Projection swings smaller than this are just weekly matchup noise.
PROJECTION_SWING_POINTS = 3.0
# Plenty for a week's worth of moves; keeps the stored JSON bounded even
# in a deep league where hundreds of free agents churn.
MAX_CHANGES = 150

ACTIVE_STATUSES = {"ACTIVE", "NORMAL"}


def snapshot_players(db: Session, league_id: int) -> dict[int, dict]:
    """Capture the current player pool keyed by ESPN player id. Must be
    called before the sync wipes Player/RosterEntry/Team rows."""
    owner_by_player_id = {
        player_id: team_name
        for player_id, team_name in db.query(RosterEntry.player_id, Team.name)
        .join(Team, RosterEntry.team_id == Team.id)
        .filter(Team.league_id == league_id)
        .all()
    }

    snapshot: dict[int, dict] = {}
    for player in db.query(Player).filter(Player.league_id == league_id).all():
        snapshot[player.espn_player_id] = {
            "name": player.full_name,
            "position": player.position,
            "injury_status": player.injury_status,
            "percent_owned": player.percent_owned,
            "projected_points": player.projected_points,
            "is_free_agent": player.is_free_agent,
            "owner": owner_by_player_id.get(player.id),
        }
    return snapshot


def _significance(change: dict) -> float:
    """Sort key — injuries to owned players first, then roster moves, then
    the numeric swings by size."""
    kind_weight = {"injury": 1000.0, "roster_move": 500.0, "ownership": 100.0, "projection": 50.0}
    return kind_weight.get(change["kind"], 0.0) + abs(change.get("magnitude") or 0.0)


def diff_players(before: dict[int, dict], after: dict[int, dict]) -> list[dict]:
    """Compare two snapshot_players()-shaped dicts into a flat change list."""
    changes: list[dict] = []

    for espn_player_id, new in after.items():
        old = before.get(espn_player_id)
        if old is None:
            continue  # newly visible in the player pool, not a change to report

        base = {
            "espn_player_id": espn_player_id,
            "name": new["name"],
            "position": new["position"],
            "owner": new["owner"],
        }

        old_status = old["injury_status"]
        new_status = new["injury_status"]
        if old_status != new_status and not (old_status in ACTIVE_STATUSES and new_status in ACTIVE_STATUSES):
            changes.append(
                {
                    **base,
                    "kind": "injury",
                    "detail": f"{old_status} to {new_status}",
                    "from": old_status,
                    "to": new_status,
                    "magnitude": 0.0 if new_status in ACTIVE_STATUSES else 1.0,
                }
            )

        if old["owner"] != new["owner"]:
            if old["owner"] is None and new["owner"] is not None:
                detail = f"added by {new['owner']}"
            elif new["owner"] is None and old["owner"] is not None:
                detail = f"dropped by {old['owner']}"
            else:
                detail = f"moved from {old['owner']} to {new['owner']}"
            changes.append(
                {**base, "kind": "roster_move", "detail": detail, "from": old["owner"], "to": new["owner"], "magnitude": 0.0}
            )

        owned_delta = (new["percent_owned"] or 0.0) - (old["percent_owned"] or 0.0)
        if abs(owned_delta) >= OWNERSHIP_JUMP_PCT:
            direction = "up" if owned_delta > 0 else "down"
            changes.append(
                {
                    **base,
                    "kind": "ownership",
                    "detail": f"rostered {direction} {abs(owned_delta):.0f} pts to {new['percent_owned']:.0f}%",
                    "from": old["percent_owned"],
                    "to": new["percent_owned"],
                    "magnitude": owned_delta,
                }
            )

        old_proj, new_proj = old["projected_points"], new["projected_points"]
        if old_proj is not None and new_proj is not None:
            proj_delta = new_proj - old_proj
            if abs(proj_delta) >= PROJECTION_SWING_POINTS:
                direction = "up" if proj_delta > 0 else "down"
                changes.append(
                    {
                        **base,
                        "kind": "projection",
                        "detail": f"projection {direction} {abs(proj_delta):.1f} to {new_proj:.1f}",
                        "from": old_proj,
                        "to": new_proj,
                        "magnitude": proj_delta,
                    }
                )

    changes.sort(key=_significance, reverse=True)
    return changes[:MAX_CHANGES]
