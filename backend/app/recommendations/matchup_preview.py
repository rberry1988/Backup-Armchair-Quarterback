"""This week's head-to-head: who you're playing, how the two projected
lineups compare, and what would most move the result.

The projected margin is the honest number here. The win probability is a
translation of it, and is only as good as its assumption about how much a
fantasy team's actual score swings around its projection — see
TEAM_WEEK_STDEV. It's reported to make the margin interpretable ("up 8" is
a very different position in a low-scoring league than a high-scoring one),
not because it's precise.
"""

from __future__ import annotations

import math

from sqlalchemy.orm import Session

from app.espn_constants import is_bench_slot
from app.espn_league_settings import opponent_for
from app.matchup import get_matchup_context
from app.models import League, Team
from app.recommendations.common import get_my_team, points_or_default, roster_with_players
from app.recommendations.start_sit import get_start_sit

# How much a fantasy team's real weekly score typically differs from its
# projection, in points. Deliberately a single documented constant rather
# than something derived per league: weekly team totals aren't stored
# (rosters only reflect right now), so any "empirical" figure here would be
# reconstructed from incomplete history and would look more authoritative
# than it is. ~25 points is the usual spread quoted for full-PPR scoring.
# The UI says this is an approximation for exactly this reason.
TEAM_WEEK_STDEV = 25.0


def _win_probability(margin: float) -> float:
    """P(you outscore them), as a percentage.

    Both teams' scores are treated as independent draws around their
    projections, so the margin's own spread is sqrt(2) times one team's.
    """
    spread = TEAM_WEEK_STDEV * math.sqrt(2)
    # Normal CDF via erf — no scipy in this project, and this is the only
    # place that needs it.
    probability = 0.5 * (1 + math.erf(margin / (spread * math.sqrt(2))))
    return round(probability * 100, 1)


def _lineup_for(db: Session, league: League | None, team: Team) -> tuple[list[dict], float]:
    """A team's current starters and their combined projection."""
    starters = [e for e in roster_with_players(db, team.id) if not is_bench_slot(e.lineup_slot_id)]
    rows = []
    total = 0.0
    for entry in starters:
        player = entry.player
        points = points_or_default(player)
        total += points
        rows.append(
            {
                "slot": entry.lineup_slot,
                "slot_id": entry.lineup_slot_id,
                "name": player.full_name,
                "position": player.position,
                "projected_points": player.projected_points,
                "injury_status": player.injury_status,
                "matchup": get_matchup_context(league, player.pro_team_id, player.position) if league else None,
            }
        )
    return rows, round(total, 1)


def _team_summary(team: Team, lineup: list[dict], projected: float) -> dict:
    return {
        "team_id": team.espn_team_id,
        "name": team.name,
        "record": f"{team.wins}-{team.losses}" + (f"-{team.ties}" if team.ties else ""),
        "projected": projected,
        "lineup": lineup,
    }


def _biggest_swing(db: Session, league_id: int, my_team_id: int, margin: float) -> dict | None:
    """The single lineup change that most improves your odds.

    Reuses the start/sit solver rather than re-deriving it, so the swap
    suggested here can never disagree with the one on that tab.
    """
    start_sit = get_start_sit(db, league_id, my_team_id)
    if "error" in start_sit:
        return None

    best = None
    for row in start_sit.get("lineup", []):
        if not row.get("swap_recommended"):
            continue
        gain = points_or_default_value(row["recommended_starter"]) - points_or_default_value(row["current_starter"])
        if gain <= 0:
            continue
        if best is None or gain > best["gain"]:
            best = {
                "slot": row["slot"],
                "out": row["current_starter"]["name"],
                "in": row["recommended_starter"]["name"],
                "gain": round(gain, 1),
            }

    if best is None:
        return None
    best["win_probability_after"] = _win_probability(margin + best["gain"])
    return best


def points_or_default_value(player_payload: dict) -> float:
    """points_or_default for an already-serialised start/sit player."""
    points = player_payload.get("projected_points")
    return float(points) if points is not None else 0.0


def get_matchup_preview(db: Session, league_id: int, my_team_id: int) -> dict:
    team = get_my_team(db, league_id, my_team_id)
    if team is None:
        return {"error": "team_not_found"}

    league = db.get(League, league_id)
    week = league.current_week if league else None
    schedule = (league.fantasy_schedule or {}) if league else {}

    my_lineup, my_projected = _lineup_for(db, league, team)

    opponent_id = opponent_for(schedule, my_team_id, week) if week else None
    if opponent_id is None:
        # No schedule yet (synced before it was captured), or a genuine bye
        # in an odd-sized league. Either way there's nothing to compare
        # against, and inventing an opponent would be worse than saying so.
        return {
            "week": week,
            "me": _team_summary(team, my_lineup, my_projected),
            "opponent": None,
            "schedule_available": bool(schedule),
        }

    opponent = (
        db.query(Team).filter(Team.league_id == league_id, Team.espn_team_id == opponent_id).first()
    )
    if opponent is None:
        return {
            "week": week,
            "me": _team_summary(team, my_lineup, my_projected),
            "opponent": None,
            "schedule_available": bool(schedule),
        }

    opp_lineup, opp_projected = _lineup_for(db, league, opponent)
    margin = round(my_projected - opp_projected, 1)

    return {
        "week": week,
        "me": _team_summary(team, my_lineup, my_projected),
        "opponent": _team_summary(opponent, opp_lineup, opp_projected),
        "margin": margin,
        "win_probability": _win_probability(margin),
        "biggest_swing": _biggest_swing(db, league_id, my_team_id, margin),
        "schedule_available": True,
        # So the UI can be honest about where the probability comes from.
        "stdev_assumed": TEAM_WEEK_STDEV,
    }
