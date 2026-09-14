"""Floor, ceiling, and boom/bust rates from a player's own season.

A 14-point average hides the difference between a player who scores 13-15
every week and one who alternates 4 and 24. Which you want depends on the
week: chasing a favorite wants ceiling, protecting a lead wants floor.

Thresholds here are relative to the player's own average rather than
position-wide cutoffs — no scoring-format calibration to get wrong, and
"blew up relative to his normal game" is the question being asked anyway.
"""

from __future__ import annotations

import statistics
from collections import defaultdict

from sqlalchemy.orm import Session

from app.models import PlayerWeekStat

MIN_WEEKS = 3
BOOM_MULTIPLIER = 1.5
BUST_MULTIPLIER = 0.5
# Coefficient of variation (stdev / mean) cutoffs for the headline label.
STEADY_CV = 0.35
VOLATILE_CV = 0.65


def _played_weeks(rows: list[PlayerWeekStat]) -> list[tuple[int, float]]:
    """(week, actual_points) for weeks the player actually played.

    A bye or inactive week is stored as a row too, usually with no points
    and no counting stats — counting those as zeros would tank every
    floor in the app, so a week only counts when there's real evidence of
    a game: raw stats recorded, or a nonzero score.
    """
    played = []
    for row in rows:
        if row.actual_points is None:
            continue
        if not row.raw_stats_actual and row.actual_points == 0:
            continue
        played.append((row.week, row.actual_points))
    return sorted(played)


def _summarize(rows: list[PlayerWeekStat]) -> dict | None:
    played = _played_weeks(rows)
    if len(played) < MIN_WEEKS:
        return None

    points = [p for _, p in played]
    average = sum(points) / len(points)
    stdev = statistics.pstdev(points) if len(points) > 1 else 0.0

    booms = sum(1 for p in points if average > 0 and p >= average * BOOM_MULTIPLIER)
    busts = sum(1 for p in points if average > 0 and p <= average * BUST_MULTIPLIER)

    if average <= 0:
        label = "unrated"
    else:
        cv = stdev / average
        if cv <= STEADY_CV:
            label = "steady"
        elif cv >= VOLATILE_CV:
            label = "boom/bust"
        else:
            label = "streaky"

    return {
        "weeks_counted": len(points),
        "average": round(average, 1),
        "floor": round(min(points), 1),
        "ceiling": round(max(points), 1),
        "stdev": round(stdev, 1),
        "boom_rate": round(booms / len(points) * 100),
        "bust_rate": round(busts / len(points) * 100),
        "label": label,
    }


def get_consistency(db: Session, league_id: int, espn_player_ids: list[int]) -> dict[int, dict | None]:
    """Batched: one query for every requested player's week history, the
    same shape as app/trends.py so a whole roster renders in one round
    trip instead of one per player."""
    if not espn_player_ids:
        return {}

    rows_by_player: dict[int, list[PlayerWeekStat]] = defaultdict(list)
    all_rows = (
        db.query(PlayerWeekStat)
        .filter(PlayerWeekStat.league_id == league_id, PlayerWeekStat.espn_player_id.in_(espn_player_ids))
        .all()
    )
    for row in all_rows:
        rows_by_player[row.espn_player_id].append(row)

    return {espn_id: _summarize(rows_by_player.get(espn_id, [])) for espn_id in espn_player_ids}
