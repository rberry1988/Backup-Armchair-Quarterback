"""This week's matchup as it actually stands right now.

The rest of the app is a planning tool: everything it says is computed
from a snapshot taken at sync time. This module is the exception. It reads
the live boxscore and the live NFL scoreboard on every request, because a
score that is five minutes stale is worse than no score at all.

The win probability here is a genuinely better estimate than the pre-game
one, and for a reason worth stating: points already scored carry no
uncertainty. As players finish, the spread of possible final scores
narrows toward zero, so the number converges on the real outcome instead
of hovering near its pre-game guess.
"""

from __future__ import annotations

import logging
import math

from sqlalchemy.orm import Session

from app.bench_points import extract_team_lineup
from app.espn_constants import is_bench_slot
from app.espn_client import ESPNClient, ESPNClientError, fetch_game_states
from app.espn_league_settings import opponent_for
from app.models import League, Player, Team, User
from app.recommendations.common import get_my_team
from app.recommendations.matchup_preview import TEAM_WEEK_STDEV

logger = logging.getLogger(__name__)

# Players whose game hasn't kicked off yet still carry their full
# pre-game uncertainty; ones mid-game carry roughly half of it, since part
# of their day is already on the board. A blunt split, but it beats
# treating a player in the fourth quarter the same as one playing tomorrow.
IN_PROGRESS_UNCERTAINTY = 0.5


def _win_probability(margin: float, remaining_share: float) -> float:
    """P(you win), given the current margin and how much of the day's
    projected scoring is still unplayed.

    remaining_share of 1.0 is kickoff (full pre-game spread); 0.0 is every
    game final, where the margin simply decides it.
    """
    if remaining_share <= 0:
        return 100.0 if margin > 0 else (0.0 if margin < 0 else 50.0)
    spread = TEAM_WEEK_STDEV * math.sqrt(2) * math.sqrt(remaining_share)
    probability = 0.5 * (1 + math.erf(margin / (spread * math.sqrt(2))))
    return round(probability * 100, 1)


def _side(lineup: list[dict], projections: dict[int, float], states: dict[int, dict],
          pro_teams: dict[int, int]) -> dict:
    """One team's live position: what's banked, what's still coming, and
    the per-player detail behind both."""
    players = []
    banked = 0.0
    remaining_projection = 0.0
    weighted_remaining = 0.0
    yet_to_play = 0
    in_progress = 0

    for entry in lineup:
        if is_bench_slot(entry["slot_id"]):
            continue
        espn_id = entry.get("espn_player_id")
        pro_team_id = pro_teams.get(espn_id)
        state_info = states.get(pro_team_id) if pro_team_id else None
        state = (state_info or {}).get("state") or "pre"
        points = float(entry.get("points") or 0.0)
        projected = float(projections.get(espn_id) or 0.0)

        banked += points
        if state == "post":
            pass  # done: no further contribution, no further uncertainty
        elif state == "in":
            in_progress += 1
            # Already part-way through their day, so only the unscored part
            # of the projection is still "coming".
            still_coming = max(0.0, projected - points)
            remaining_projection += still_coming
            weighted_remaining += still_coming * IN_PROGRESS_UNCERTAINTY
        else:
            yet_to_play += 1
            remaining_projection += projected
            weighted_remaining += projected

        players.append(
            {
                "name": entry["name"],
                "slot": entry["slot"],
                "position": entry["position"],
                "points": round(points, 1),
                "projected_points": round(projected, 1) if projected else None,
                "state": state,
                "detail": (state_info or {}).get("detail") or "",
            }
        )

    return {
        "players": players,
        "banked": round(banked, 1),
        "remaining_projection": round(remaining_projection, 1),
        "estimate": round(banked + remaining_projection, 1),
        "yet_to_play": yet_to_play,
        "in_progress": in_progress,
        "_weighted_remaining": weighted_remaining,
    }


def get_live_matchup(db: Session, league: League, my_team_id: int, user: User | None = None) -> dict:
    """Live scores for both sides of this week's matchup.

    Returns {"available": False, "reason": ...} rather than raising when
    there's nothing to show — before kickoff, on a bye, or when ESPN is
    unreachable. The Matchup tab keeps its pre-game view in those cases.
    """
    team = get_my_team(db, league.id, my_team_id)
    if team is None:
        return {"available": False, "reason": "team_not_found"}

    week = league.current_week
    opponent_id = opponent_for(league.fantasy_schedule or {}, my_team_id, week) if week else None
    if opponent_id is None:
        return {"available": False, "reason": "no_opponent"}

    opponent = (
        db.query(Team).filter(Team.league_id == league.id, Team.espn_team_id == opponent_id).first()
    )
    if opponent is None:
        return {"available": False, "reason": "no_opponent"}

    client = ESPNClient(
        league_id=league.espn_league_id,
        season=league.season,
        espn_s2=user.espn_s2 if user else None,
        espn_swid=user.espn_swid if user else None,
    )
    try:
        boxscore = client.get_boxscore(week)
    except ESPNClientError as exc:
        logger.info("Live boxscore unavailable for league %s: %s", league.id, exc)
        return {"available": False, "reason": "espn_unavailable", "detail": str(exc)}

    my_lineup = extract_team_lineup(boxscore, my_team_id, week)
    opp_lineup = extract_team_lineup(boxscore, opponent_id, week)
    if not my_lineup or not opp_lineup:
        return {"available": False, "reason": "no_boxscore"}

    # Projections and NFL teams come from the synced player pool; the
    # boxscore carries live points but not the pre-game projection we need
    # to estimate what's still to come.
    rows = db.query(Player.espn_player_id, Player.projected_points, Player.pro_team_id).filter(
        Player.league_id == league.id
    )
    projections = {espn_id: proj or 0.0 for espn_id, proj, _ in rows}
    rows = db.query(Player.espn_player_id, Player.pro_team_id).filter(Player.league_id == league.id)
    pro_teams = {espn_id: pro_team for espn_id, pro_team in rows}

    states = fetch_game_states(week, league.season)
    mine = _side(my_lineup, projections, states, pro_teams)
    theirs = _side(opp_lineup, projections, states, pro_teams)

    # Nothing has kicked off: the pre-game view already says this better.
    if not states or all(s.get("state") == "pre" for s in states.values()):
        return {"available": False, "reason": "not_started"}

    margin = round(mine["estimate"] - theirs["estimate"], 1)
    # How much of the day's projected scoring is still genuinely uncertain,
    # across both teams. This is what shrinks the spread as games finish.
    total_projection = sum(projections.get(p.get("espn_player_id"), 0.0)
                           for lineup in (my_lineup, opp_lineup)
                           for p in lineup if not is_bench_slot(p["slot_id"])) or 1.0
    remaining_share = min(1.0, (mine["_weighted_remaining"] + theirs["_weighted_remaining"]) / total_projection)

    for side in (mine, theirs):
        side.pop("_weighted_remaining", None)

    return {
        "available": True,
        "week": week,
        "me": {"name": team.name, **mine},
        "opponent": {"name": opponent.name, **theirs},
        "margin": margin,
        "win_probability": _win_probability(margin, remaining_share),
        # True while any game in the league's week is still running, which
        # is what tells the UI whether to keep polling.
        "in_progress": any(s.get("state") == "in" for s in states.values()),
        "remaining_share": round(remaining_share, 3),
    }
