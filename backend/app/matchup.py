"""Matchup-difficulty proxy: how tough is a player's opponent this week?

We don't have per-position "points allowed" data (that needs full box-score
history we don't collect), so we use each opponent's own projected D/ST
fantasy score, ranked across the league, as a stand-in for defensive
strength — a defense projected to score a lot of fantasy points (via
sacks/turnovers/a strong performance) is generally a tougher matchup for
the offense it's facing. It's an approximation, not a real
points-allowed-by-position model.
"""

from __future__ import annotations

from app.models import League


def get_matchup_context(league: League, pro_team_id: int | None) -> dict | None:
    if not pro_team_id or not league.schedule or not league.dst_projected_points:
        return None

    info = league.schedule.get(str(pro_team_id))
    if not info or info.get("opponent_id") is None:
        return None

    dst_scores = league.dst_projected_points
    opponent_id = info["opponent_id"]
    opponent_score = dst_scores.get(str(opponent_id))
    if opponent_score is None:
        return None

    ranked = sorted(dst_scores.values(), reverse=True)  # higher projected D/ST score = tougher defense
    rank = ranked.index(opponent_score) + 1
    total = len(ranked)
    third = max(1, total // 3)

    if rank <= third:
        label = "tough matchup"
    elif rank > total - third:
        label = "favorable matchup"
    else:
        label = "average matchup"

    return {
        "opponent": info.get("opponent_abbreviation"),
        "defense_rank": rank,
        "defense_teams_ranked": total,
        "label": label,
    }
