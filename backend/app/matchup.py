"""How tough is a player's opponent this week?

Three sources, best first, each falling through to the next when the data
isn't there:

1. Real per-game yardage the opponent allows to this position, from
   nflverse's weekly stats — rushing yards to RBs, receiving to WRs and
   TEs, passing to QBs (app/advanced_stats.py). This both ranks the
   matchup and explains it, because it's the underlying thing rather than
   a restatement of the projection.
2. Average PPR points allowed per game to the position. Ranks as well as
   yardage but explains poorly — "allows 24.6 points to WRs" is circular
   when the question is whether to trust a points projection. Used for
   leagues synced before (1) existed, and for K and D/ST, which have no
   meaningful yardage stat.
3. The opponent's own projected D/ST fantasy score, ranked league-wide —
   a crude stand-in for when nflverse was unreachable at sync time or the
   season is too young to have data.
"""

from __future__ import annotations

from app.espn_constants import team_abbr_candidates
from app.models import League


def _team_entry(table: dict, abbr: str | None):
    """This team's row from a defensive table, trying every spelling of its
    abbreviation (see espn_constants.team_abbr_candidates) — a league synced
    before abbreviations were normalised still has nflverse's LA/WAS on
    disk, and silently missing them is how the Rams and Commanders went
    unrated."""
    for candidate in team_abbr_candidates(abbr):
        entry = table.get(candidate)
        if entry:
            return entry
    return None


def _rank_and_label(value: float, all_values: list[float], higher_is_tougher: bool) -> tuple[int, int, str]:
    ranked = sorted(all_values, reverse=higher_is_tougher)
    rank = ranked.index(value) + 1
    total = len(ranked)
    third = max(1, total // 3)
    if rank <= third:
        label = "tough matchup"
    elif rank > total - third:
        label = "favorable matchup"
    else:
        label = "average matchup"
    return rank, total, label


def get_matchup_context(league: League, pro_team_id: int | None, position: str | None = None) -> dict | None:
    if not pro_team_id or not league.schedule:
        return None

    info = league.schedule.get(str(pro_team_id))
    if not info or info.get("opponent_id") is None:
        return None
    return rate_opponent(league, info.get("opponent_abbreviation"), info["opponent_id"], position)


def rate_opponent(
    league: League, opponent_abbr: str | None, opponent_id: int | None, position: str | None = None
) -> dict | None:
    """How tough is this specific opponent for `position`? Split out from
    get_matchup_context() so future weeks (app/schedule_outlook.py) can be
    rated the same way as the current one."""
    defense = league.defense_vs_position or {}
    opponent_defense = _team_entry(defense, opponent_abbr) or {}
    if position and position in opponent_defense:
        all_entries = [
            team_positions[position] for team_positions in defense.values() if position in team_positions
        ]
        all_values = [e["yards"] for e in all_entries if e.get("yards") is not None]
        entry = opponent_defense[position]
        if entry.get("yards") is not None and len(all_values) >= 4:
            # Fewer yards allowed = a stingier, tougher defense; more
            # allowed = an easier matchup for the offense.
            rank, total, label = _rank_and_label(entry["yards"], all_values, higher_is_tougher=False)
            all_tds = [e["tds"] for e in all_entries if e.get("tds") is not None]
            return {
                "opponent": opponent_abbr,
                "defense_rank": rank,
                "defense_teams_ranked": total,
                "label": label,
                "source": "yards_allowed",
                # The numbers the label came from, so the UI can show its
                # working rather than asking anyone to take "tough" on faith.
                "position": position,
                "value": entry["yards"],
                "league_average": round(sum(all_values) / len(all_values), 1),
                "metric": entry.get("metric", "yds"),
                "tds": entry.get("tds"),
                "tds_league_average": round(sum(all_tds) / len(all_tds), 2) if all_tds else None,
                "games": entry.get("games"),
            }

    points_allowed = league.points_allowed_by_position or {}
    opponent_points = _team_entry(points_allowed, opponent_abbr) or {}
    if position and position in opponent_points:
        all_values = [
            team_positions[position] for team_positions in points_allowed.values() if position in team_positions
        ]
        if len(all_values) >= 4:  # too few teams to rank meaningfully otherwise
            value = opponent_points[position]
            rank, total, label = _rank_and_label(value, all_values, higher_is_tougher=False)
            return {
                "opponent": opponent_abbr,
                "defense_rank": rank,
                "defense_teams_ranked": total,
                "label": label,
                "source": "points_allowed",
                "position": position,
                "value": round(value, 1),
                "league_average": round(sum(all_values) / len(all_values), 1),
                "metric": "fantasy pts",
            }

    dst_scores = league.dst_projected_points or {}
    opponent_score = dst_scores.get(str(opponent_id)) if opponent_id is not None else None
    if opponent_score is None:
        return None
    # Higher D/ST projected score = a stronger, tougher defense.
    all_scores = list(dst_scores.values())
    rank, total, label = _rank_and_label(opponent_score, all_scores, higher_is_tougher=True)
    return {
        "opponent": opponent_abbr,
        "defense_rank": rank,
        "defense_teams_ranked": total,
        "label": label,
        "source": "dst_projection",
        "position": position,
        "value": round(opponent_score, 1),
        "league_average": round(sum(all_scores) / len(all_scores), 1) if all_scores else None,
        "metric": "projected D/ST pts",
    }
