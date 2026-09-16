"""Where this season is actually heading.

A 2-1 record means very different things depending on who you've played
and who's left. This simulates the rest of the fantasy schedule many
times over and reports how often each team makes the playoffs, which
turns every waiver and trade decision into a question with a number
attached: does this move my odds?

Team strength comes from points scored per game so far, not from the
win-loss record. Fantasy records are famously noisy -- the highest-scoring
team in a league is routinely 2-3 because of who it drew each week -- and
simulating from the record would launder that noise into a forecast.
"""

from __future__ import annotations

import random

from sqlalchemy.orm import Session

from app.espn_league_settings import opponent_for
from app.models import League, Team

# Enough runs that the reported percentage is stable to about a point,
# while staying comfortably inside a single request. Seeded per call so
# the same league state always gives the same answer -- odds that jitter
# on refresh read as broken however correct they are.
SIMULATIONS = 2000
RANDOM_SEED = 20240

# Spread of a team's weekly score around its own average, in points. Same
# figure the matchup preview uses and for the same reason: weekly team
# totals aren't stored, so this is a documented assumption rather than a
# fabricated per-league measurement.
WEEKLY_STDEV = 25.0

# Default playoff field when the league's own setting isn't available.
DEFAULT_PLAYOFF_TEAMS = 6


def _strength(team: Team, games_played: int, league_average: float) -> float:
    """Points per game, regressed toward the league average early on.

    Three weeks of scoring is a small sample, and taking it at face value
    would hand a hot start far more predictive weight than it has earned.
    The weight on a team's own scoring grows as the season does.
    """
    if games_played <= 0:
        return league_average
    own = team.points_for / games_played
    # Full credit by roughly mid-season; heavily regressed in week 1.
    confidence = min(1.0, games_played / 8.0)
    return own * confidence + league_average * (1 - confidence)


def _remaining_weeks(schedule: dict, current_week: int, regular_season_weeks: int) -> list[int]:
    weeks = []
    for raw in schedule or {}:
        try:
            week = int(raw)
        except (TypeError, ValueError):
            continue
        if current_week <= week <= regular_season_weeks:
            weeks.append(week)
    return sorted(weeks)


def get_playoff_odds(db: Session, league_id: int, my_team_id: int) -> dict:
    league = db.get(League, league_id)
    if league is None:
        return {"available": False, "reason": "league_not_found"}

    teams = db.query(Team).filter(Team.league_id == league_id).all()
    if len(teams) < 2:
        return {"available": False, "reason": "no_teams"}

    schedule = league.fantasy_schedule or {}
    if not schedule:
        return {"available": False, "reason": "no_schedule"}

    current_week = league.current_week or 1
    # The last week anyone plays a regular-season game, taken from the
    # schedule itself rather than assumed -- league lengths vary.
    regular_season_weeks = max((int(w) for w in schedule if str(w).isdigit()), default=current_week)
    remaining = _remaining_weeks(schedule, current_week, regular_season_weeks)

    games_played = [t.wins + t.losses + t.ties for t in teams]
    max_played = max(games_played) if games_played else 0
    total_points = sum(t.points_for for t in teams)
    league_average = (total_points / sum(games_played)) if sum(games_played) else 100.0

    strength = {t.espn_team_id: _strength(t, t.wins + t.losses + t.ties, league_average) for t in teams}
    base_wins = {t.espn_team_id: t.wins + 0.5 * t.ties for t in teams}
    playoff_teams = min(DEFAULT_PLAYOFF_TEAMS, max(2, len(teams) // 2))

    rng = random.Random(RANDOM_SEED)
    made = {t.espn_team_id: 0 for t in teams}
    final_wins = {t.espn_team_id: 0.0 for t in teams}

    for _ in range(SIMULATIONS):
        wins = dict(base_wins)
        for week in remaining:
            for home, away in schedule.get(str(week), []):
                if home not in wins or away not in wins:
                    continue
                home_score = rng.gauss(strength[home], WEEKLY_STDEV)
                away_score = rng.gauss(strength[away], WEEKLY_STDEV)
                if home_score >= away_score:
                    wins[home] += 1
                else:
                    wins[away] += 1

        # Seeded by wins, with total scoring as the tiebreak — the near
        # universal fantasy convention, and the only tiebreak we can
        # actually evaluate from what's stored.
        ranked = sorted(wins, key=lambda tid: (wins[tid], strength[tid]), reverse=True)
        for tid in ranked[:playoff_teams]:
            made[tid] += 1
        for tid, w in wins.items():
            final_wins[tid] += w

    by_id = {t.espn_team_id: t for t in teams}

    def row(tid: int) -> dict:
        team = by_id[tid]
        # Strength of what's left: the average scoring of the opponents
        # this team still has to face, relative to the league.
        opponents = []
        for week in remaining:
            other = opponent_for(schedule, tid, week)
            if other in strength:
                opponents.append(strength[other])
        sos = round(sum(opponents) / len(opponents), 1) if opponents else None
        return {
            "team_id": tid,
            "team": team.name,
            "record": f"{team.wins}-{team.losses}" + (f"-{team.ties}" if team.ties else ""),
            "points_per_game": round(strength[tid], 1),
            "playoff_odds": round(made[tid] / SIMULATIONS * 100, 1),
            "projected_wins": round(final_wins[tid] / SIMULATIONS, 1),
            "remaining_opponent_ppg": sos,
            # Positive means a harder run-in than the league average.
            "schedule_difficulty": round(sos - league_average, 1) if sos is not None else None,
            "is_me": tid == my_team_id,
        }

    standings = sorted((row(t.espn_team_id) for t in teams), key=lambda r: -r["playoff_odds"])
    me = next((r for r in standings if r["is_me"]), None)

    return {
        "available": True,
        "week": current_week,
        "playoff_teams": playoff_teams,
        "weeks_remaining": len(remaining),
        "simulations": SIMULATIONS,
        "league_average_ppg": round(league_average, 1),
        "standings": standings,
        "me": me,
        # Honest about the sample: early-season odds rest on very little.
        "games_played": max_played,
    }
