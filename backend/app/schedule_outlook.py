"""Looking past this Sunday: multi-week matchup difficulty, bye-week
collisions, and fantasy-playoff schedule strength.

The current-week matchup tags (app/matchup.py) answer "start him this
week?". These answer the questions that actually drive trades and stashes:
who has a brutal next month, which weeks does my roster fall apart on
byes, and whose schedule opens up exactly when the fantasy playoffs start.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.espn_constants import pro_team_abbr
from app.matchup import rate_opponent
from app.models import League, Player, RosterEntry, Team

DEFAULT_WEEKS_AHEAD = 4
# Weeks 15-17 are the default fantasy playoffs in ESPN's standard format
# (week 18 is usually skipped since NFL teams rest starters).
PLAYOFF_WEEKS = [15, 16, 17]

# Maps a rating label to a comparable number so a stretch of weeks can be
# averaged into one "how good is this schedule" score.
LABEL_SCORES = {"favorable matchup": 1.0, "average matchup": 0.0, "tough matchup": -1.0}


def _week_entry(league: League, pro_team_id: int, week: int, position: str) -> dict:
    """One player's game (or bye) in a given week, rated."""
    teams_this_week = (league.season_schedule or {}).get(str(week), {})
    info = teams_this_week.get(str(pro_team_id))
    if not info:
        return {"week": week, "is_bye": True, "opponent": None, "label": None}

    rating = rate_opponent(league, info.get("opponent_abbreviation"), info.get("opponent_id"), position)
    return {
        "week": week,
        "is_bye": False,
        "opponent": info.get("opponent_abbreviation"),
        "label": rating["label"] if rating else None,
        "defense_rank": rating["defense_rank"] if rating else None,
        "defense_teams_ranked": rating["defense_teams_ranked"] if rating else None,
    }


def _summarize(weeks: list[dict]) -> dict:
    """Average the rated (non-bye) weeks into a single schedule score."""
    scores = [LABEL_SCORES[w["label"]] for w in weeks if w.get("label") in LABEL_SCORES]
    byes = sum(1 for w in weeks if w["is_bye"])
    if not scores:
        return {"score": None, "label": None, "byes": byes}
    average = sum(scores) / len(scores)
    if average >= 0.34:
        label = "favorable stretch"
    elif average <= -0.34:
        label = "tough stretch"
    else:
        label = "average stretch"
    return {"score": round(average, 2), "label": label, "byes": byes}


def get_schedule_outlook(
    db: Session, league_id: int, my_team_id: int, weeks_ahead: int = DEFAULT_WEEKS_AHEAD
) -> dict:
    """Per rostered player: the next `weeks_ahead` games rated, plus their
    fantasy-playoff-weeks schedule, plus a roster-wide bye-week planner."""
    league = db.get(League, league_id)
    if league is None:
        return {"error": "league_not_found"}

    team = (
        db.query(Team).filter(Team.league_id == league_id, Team.espn_team_id == my_team_id).first()
    )
    if team is None:
        return {"error": "team_not_found"}

    players = (
        db.query(Player)
        .join(RosterEntry, RosterEntry.player_id == Player.id)
        .filter(RosterEntry.team_id == team.id)
        .all()
    )

    start_week = league.current_week or 1
    upcoming_weeks = list(range(start_week, start_week + weeks_ahead))
    bye_weeks = league.bye_weeks or {}

    outlook = []
    byes_by_week: dict[int, list[dict]] = {}
    for player in players:
        if not player.pro_team_id:
            continue
        upcoming = [_week_entry(league, player.pro_team_id, wk, player.position) for wk in upcoming_weeks]
        playoffs = [_week_entry(league, player.pro_team_id, wk, player.position) for wk in PLAYOFF_WEEKS]
        bye_week = bye_weeks.get(str(player.pro_team_id))

        outlook.append(
            {
                "espn_player_id": player.espn_player_id,
                "name": player.full_name,
                "position": player.position,
                "pro_team": pro_team_abbr(player.pro_team_id),
                "bye_week": bye_week,
                "upcoming": upcoming,
                "upcoming_summary": _summarize(upcoming),
                "playoffs": playoffs,
                "playoff_summary": _summarize(playoffs),
            }
        )

        if bye_week:
            byes_by_week.setdefault(bye_week, []).append(
                {
                    "espn_player_id": player.espn_player_id,
                    "name": player.full_name,
                    "position": player.position,
                    "pro_team": pro_team_abbr(player.pro_team_id),
                }
            )

    # Sort worst-upcoming-schedule first so the players worth acting on are
    # at the top rather than buried in roster order.
    outlook.sort(key=lambda p: (p["upcoming_summary"]["score"] is None, p["upcoming_summary"]["score"] or 0.0))

    return {
        "team": team.name,
        "current_week": start_week,
        "weeks_ahead": weeks_ahead,
        "playoff_weeks": PLAYOFF_WEEKS,
        "available": bool(league.season_schedule),
        "outlook": outlook,
        "byes": _bye_planner(byes_by_week, league.roster_slot_counts or {}, start_week),
    }


def _bye_planner(byes_by_week: dict[int, list[dict]], roster_slot_counts: dict, current_week: int) -> list[dict]:
    """Upcoming bye weeks, flagged where enough players at one position are
    out at once to leave a starting slot uncoverable."""
    # ESPN's lineupSlotCounts is keyed by slot id; the single-position ones
    # are all we can check cleanly (FLEX-type slots draw from several).
    starters_needed = {
        "QB": int(roster_slot_counts.get("0", 0)),
        "RB": int(roster_slot_counts.get("2", 0)),
        "WR": int(roster_slot_counts.get("4", 0)),
        "TE": int(roster_slot_counts.get("6", 0)),
        "D/ST": int(roster_slot_counts.get("16", 0)),
        "K": int(roster_slot_counts.get("17", 0)),
    }

    planner = []
    for week in sorted(byes_by_week):
        if week < current_week:
            continue
        players = byes_by_week[week]
        by_position: dict[str, int] = {}
        for player in players:
            by_position[player["position"]] = by_position.get(player["position"], 0) + 1

        warnings = []
        for position, out_count in sorted(by_position.items()):
            needed = starters_needed.get(position, 0)
            if needed and out_count >= needed:
                warnings.append(
                    f"{out_count} of your {position}s are on bye — you start {needed}"
                )

        planner.append(
            {
                "week": week,
                "players": sorted(players, key=lambda p: p["position"]),
                "count": len(players),
                "warnings": warnings,
            }
        )
    return planner
