"""Trade suggestions based on positional strength/depth across the league.

Heuristic, not a full trade-value engine: for each position we estimate how
many starters a team needs (from the league's own roster slot counts,
splitting shared FLEX/OP slots across eligible positions), then rank every
team's "starting strength" (their best starters' projected points) and
"bench depth" (points sitting behind those starters) at that position.
Your weak positions are needs; your deep positions are trade chips; teams
whose depth/need profile is a mirror image of yours are good partners.
"""

from __future__ import annotations

import statistics

from sqlalchemy.orm import Session

from app.models import League, Team
from app.recommendations.common import points_or_default, roster_with_players

POSITIONS = ["QB", "RB", "WR", "TE", "K", "D/ST"]

# lineupSlotId -> positions it can be filled by, used to spread shared slots
# (FLEX, OP) across the positions that are eligible for them.
SHARED_SLOT_SHARES = {
    "23": {"RB": 0.45, "WR": 0.45, "TE": 0.10},  # FLEX
    "7": {"QB": 0.4, "RB": 0.2, "WR": 0.2, "TE": 0.2},  # OP (superflex-style)
}
PRIMARY_SLOT_TO_POSITION = {
    "0": "QB",
    "2": "RB",
    "4": "WR",
    "6": "TE",
    "16": "D/ST",
    "17": "K",
}


def _starters_needed(roster_slot_counts: dict) -> dict[str, float]:
    needed = {pos: 0.0 for pos in POSITIONS}
    for slot_id, count in roster_slot_counts.items():
        if slot_id in PRIMARY_SLOT_TO_POSITION:
            needed[PRIMARY_SLOT_TO_POSITION[slot_id]] += count
        elif slot_id in SHARED_SLOT_SHARES:
            for pos, share in SHARED_SLOT_SHARES[slot_id].items():
                needed[pos] += count * share
    return needed


def _team_position_profile(db: Session, team: Team, starters_needed: dict[str, float]) -> dict:
    entries = roster_with_players(db, team.id)
    by_position: dict[str, list[float]] = {pos: [] for pos in POSITIONS}
    for entry in entries:
        by_position.setdefault(entry.player.position, []).append(points_or_default(entry.player))

    profile = {}
    for pos in POSITIONS:
        points = sorted(by_position.get(pos, []), reverse=True)
        k = max(1, round(starters_needed.get(pos, 1)))
        starting_strength = sum(points[:k])
        bench_depth = sum(points[k:])
        profile[pos] = {"starting_strength": starting_strength, "bench_depth": bench_depth}
    return profile


def get_trade_suggestions(db: Session, league_id: int, my_team_id: int) -> dict:
    league = db.get(League, league_id)
    if league is None:
        return {"error": "league_not_found"}

    teams = db.query(Team).filter(Team.league_id == league_id).all()
    my_team = next((t for t in teams if t.espn_team_id == my_team_id), None)
    if my_team is None:
        return {"error": "team_not_found"}

    starters_needed = _starters_needed(league.roster_slot_counts or {})
    profiles = {team.id: _team_position_profile(db, team, starters_needed) for team in teams}
    my_profile = profiles[my_team.id]

    needs = []
    surpluses = []
    for pos in POSITIONS:
        league_strengths = [profiles[t.id][pos]["starting_strength"] for t in teams]
        median_strength = statistics.median(league_strengths) if league_strengths else 0
        my_strength = my_profile[pos]["starting_strength"]
        my_depth = my_profile[pos]["bench_depth"]
        league_depths = sorted(
            ((t, profiles[t.id][pos]["bench_depth"]) for t in teams), key=lambda x: x[1], reverse=True
        )
        depth_rank = next((i for i, (t, _) in enumerate(league_depths) if t.id == my_team.id), None)

        if my_strength < median_strength:
            needs.append(
                {
                    "position": pos,
                    "my_starting_strength": round(my_strength, 1),
                    "league_median": round(median_strength, 1),
                }
            )
        if depth_rank is not None and depth_rank == 0 and my_depth > 0:
            surpluses.append({"position": pos, "my_bench_depth": round(my_depth, 1)})

    # Partner suggestions: teams weak where I'm deep, and deep where I'm weak.
    partners = []
    for team in teams:
        if team.id == my_team.id:
            continue
        gives_me = []
        wants_from_me = []
        for need in needs:
            pos = need["position"]
            their_depth = profiles[team.id][pos]["bench_depth"]
            if their_depth > 0:
                gives_me.append({"position": pos, "their_bench_depth": round(their_depth, 1)})
        for surplus in surpluses:
            pos = surplus["position"]
            league_strengths = [profiles[t.id][pos]["starting_strength"] for t in teams]
            median_strength = statistics.median(league_strengths) if league_strengths else 0
            if profiles[team.id][pos]["starting_strength"] < median_strength:
                wants_from_me.append({"position": pos})
        if gives_me and wants_from_me:
            partners.append(
                {
                    "team": team.name,
                    "they_could_send": gives_me,
                    "they_might_want": wants_from_me,
                }
            )

    return {
        "team": my_team.name,
        "needs": needs,
        "surplus_to_trade": surpluses,
        "suggested_partners": partners,
    }
