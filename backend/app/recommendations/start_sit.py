"""Start/sit recommendations: a greedy best-lineup assignment.

For each of your team's starting lineup slots, we find the highest
projected-point rostered player who is eligible for that slot (considering
every other slot too, most-constrained slot first) and compare that ideal
lineup against who is actually starting.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.espn_constants import is_bench_slot
from app.matchup import get_matchup_context
from app.models import League, RosterEntry
from app.recommendations.common import (
    INJURED_OUT_STATUSES,
    get_my_team,
    points_or_default,
    roster_with_players,
)


def get_start_sit(db: Session, league_id: int, my_team_id: int) -> dict:
    team = get_my_team(db, league_id, my_team_id)
    if team is None:
        return {"error": "team_not_found"}

    league = db.get(League, league_id)

    entries = roster_with_players(db, team.id)
    starter_slots = [e for e in entries if not is_bench_slot(e.lineup_slot_id)]
    all_players_entries = entries  # a player can only fill the slot they're rostered in

    # Most-constrained-first: slots with fewer eligible bench alternatives go first.
    def eligible_candidates(slot_entry: RosterEntry) -> list[RosterEntry]:
        return [e for e in all_players_entries if slot_entry.lineup_slot_id in (e.player.eligible_slots or [])]

    slot_order = sorted(starter_slots, key=lambda e: len(eligible_candidates(e)))

    assigned_player_ids: set[int] = set()
    lineup: list[dict] = []

    for slot_entry in slot_order:
        candidates = [
            e
            for e in all_players_entries
            if slot_entry.lineup_slot_id in (e.player.eligible_slots or [])
            and e.player_id not in assigned_player_ids
        ]
        if not candidates:
            continue
        best = max(candidates, key=lambda e: points_or_default(e.player, default=-1))
        assigned_player_ids.add(best.player_id)

        current_starter = slot_entry.player
        recommended = best.player
        swap_needed = recommended.espn_player_id != current_starter.espn_player_id

        reason = None
        if swap_needed:
            if current_starter.injury_status in INJURED_OUT_STATUSES:
                reason = f"{current_starter.full_name} is {current_starter.injury_status.title()}"
            elif current_starter.projected_points is None:
                reason = f"{current_starter.full_name} has no projection this week (likely bye)"
            else:
                diff = points_or_default(recommended) - points_or_default(current_starter)
                reason = f"+{diff:.1f} projected points"

        lineup.append(
            {
                "slot": slot_entry.lineup_slot,
                "slot_id": slot_entry.lineup_slot_id,
                "current_starter": {
                    "name": current_starter.full_name,
                    "position": current_starter.position,
                    "projected_points": current_starter.projected_points,
                    "injury_status": current_starter.injury_status,
                    "matchup": get_matchup_context(league, current_starter.pro_team_id, current_starter.position)
                    if league
                    else None,
                },
                "recommended_starter": {
                    "name": recommended.full_name,
                    "position": recommended.position,
                    "projected_points": recommended.projected_points,
                    "injury_status": recommended.injury_status,
                    "matchup": get_matchup_context(league, recommended.pro_team_id, recommended.position)
                    if league
                    else None,
                },
                "swap_recommended": swap_needed,
                "reason": reason,
            }
        )

    return {
        "team": team.name,
        "week": league.current_week if league else None,
        "lineup": lineup,
        "swaps_recommended": sum(1 for row in lineup if row["swap_recommended"]),
    }
