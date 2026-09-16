"""How tough is a player's opponent this week?

Preferred source: real average PPR points allowed per game by the
opponent to the player's position, computed from nflverse's weekly stats
(app/advanced_stats.py) — the standard "matchup vs. position" rating
fantasy sites use. Falls back to a cruder proxy (the opponent's own
projected D/ST fantasy score, ranked league-wide) when nflverse data is
unavailable for that team/position/season — e.g. right after sync if
nflverse was unreachable, or very early in a season before games have
been played.
"""

from __future__ import annotations

from app.models import League


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
    points_allowed = league.points_allowed_by_position or {}
    if position and opponent_abbr in points_allowed and position in points_allowed[opponent_abbr]:
        all_values = [
            team_positions[position] for team_positions in points_allowed.values() if position in team_positions
        ]
        if len(all_values) >= 4:  # too few teams to rank meaningfully otherwise
            # Fewer points allowed = a stingier, tougher defense; more
            # allowed = an easier matchup for the offense.
            value = points_allowed[opponent_abbr][position]
            rank, total, label = _rank_and_label(value, all_values, higher_is_tougher=False)
            return {
                "opponent": opponent_abbr,
                "defense_rank": rank,
                "defense_teams_ranked": total,
                "label": label,
                "source": "points_allowed",
                # The numbers the label was derived from, so the UI can say
                # *why* a matchup is rated the way it is rather than asking
                # anyone to take "tough" on faith.
                "position": position,
                "value": round(value, 1),
                "league_average": round(sum(all_values) / len(all_values), 1),
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
    }
