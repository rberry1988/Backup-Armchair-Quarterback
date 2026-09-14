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

from app.models import League, Player, PlayerWeekStat, Team
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


def _ros_value(db: Session, league: League, espn_player_id: int) -> tuple[float, str, str]:
    """Rest-of-season value: average projected points across weeks from now
    onward that ESPN has a projection for. Falls back to the single
    current-week projection cached on Player if no snapshot history exists
    yet (e.g. right after the very first sync for a far-future week)."""
    rows = (
        db.query(PlayerWeekStat)
        .filter(
            PlayerWeekStat.league_id == league.id,
            PlayerWeekStat.espn_player_id == espn_player_id,
            PlayerWeekStat.week >= league.current_week,
            PlayerWeekStat.projected_points.isnot(None),
        )
        .all()
    )
    if rows:
        avg = sum(r.projected_points for r in rows) / len(rows)
        return avg, rows[0].full_name, rows[0].position

    player = (
        db.query(Player)
        .filter(Player.league_id == league.id, Player.espn_player_id == espn_player_id)
        .first()
    )
    if player:
        return points_or_default(player), player.full_name, player.position
    return 0.0, f"Player {espn_player_id}", "?"


def _grade_for_pct_edge(pct_edge: float) -> str:
    """pct_edge is how much value a side gained, as % of total trade value."""
    if pct_edge < 5:
        return "A"
    if pct_edge < 15:
        return "B"
    if pct_edge < 30:
        return "C"
    return "D"


def grade_trade(
    db: Session,
    league_id: int,
    team_a_espn_id: int,
    team_a_sends: list[int],
    team_b_espn_id: int,
    team_b_sends: list[int],
) -> dict:
    """Grade a proposed two-team trade using rest-of-season average
    projected points as player value, plus whether it addresses either
    side's positional needs (reusing the same need/surplus analysis as
    get_trade_suggestions).
    """
    league = db.get(League, league_id)
    if league is None:
        return {"error": "league_not_found"}

    teams = db.query(Team).filter(Team.league_id == league_id).all()
    team_a = next((t for t in teams if t.espn_team_id == team_a_espn_id), None)
    team_b = next((t for t in teams if t.espn_team_id == team_b_espn_id), None)
    if team_a is None or team_b is None:
        return {"error": "team_not_found"}

    def describe(espn_player_ids: list[int]) -> list[dict]:
        players = []
        for pid in espn_player_ids:
            value, name, position = _ros_value(db, league, pid)
            players.append({"espn_player_id": pid, "name": name, "position": position, "ros_value": round(value, 1)})
        return players

    a_sends = describe(team_a_sends)
    b_sends = describe(team_b_sends)
    a_gives_value = sum(p["ros_value"] for p in a_sends)
    b_gives_value = sum(p["ros_value"] for p in b_sends)
    total_value = a_gives_value + b_gives_value

    # Team A receives what B sends, and vice versa.
    delta_for_a = b_gives_value - a_gives_value
    pct_edge = abs(delta_for_a) / total_value * 100 if total_value > 0 else 0

    if pct_edge < 5:
        verdict = "Fair trade — close in value for both sides."
        grade_a = grade_b = "A"
    else:
        winner, loser = ("A", "B") if delta_for_a > 0 else ("B", "A")
        verdict = f"Team {winner} comes out ahead by about {pct_edge:.0f}% of the trade's total value."
        grades = {winner: "A", loser: _grade_for_pct_edge(pct_edge)}
        grade_a, grade_b = grades["A"], grades["B"]

    def need_notes(team_espn_id: int, received: list[dict]) -> list[str]:
        context = get_trade_suggestions(db, league_id, team_espn_id)
        need_positions = {n["position"] for n in context.get("needs", [])}
        notes = [f"Addresses their need at {p['position']}" for p in received if p["position"] in need_positions]
        return notes

    return {
        "team_a": {
            "name": team_a.name,
            "sends": a_sends,
            "receives": b_sends,
            "value_sent": round(a_gives_value, 1),
            "value_received": round(b_gives_value, 1),
            "grade": grade_a,
            "notes": need_notes(team_a_espn_id, b_sends),
        },
        "team_b": {
            "name": team_b.name,
            "sends": b_sends,
            "receives": a_sends,
            "value_sent": round(b_gives_value, 1),
            "value_received": round(a_gives_value, 1),
            "grade": grade_b,
            "notes": need_notes(team_b_espn_id, a_sends),
        },
        "verdict": verdict,
    }
