"""Usage-trend tracking: targets, carries, target share, snap %, and similar
opportunity stats move before fantasy points do, so surfacing the last few
weeks' values (and whether they're rising or falling) is often a better
early signal than points alone — this is what waiver-wire "buy low / sell
high" calls are usually based on.

Two sources feed this: ESPN's own raw counting stats (targets, carries, ...
— see scoring.py) and nflverse's advanced metrics (target share, snap %,
... — see advanced_stats.py), the latter only present when a player has a
crosswalk match and nflverse was reachable at sync time.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import PlayerWeekStat

# Which stats matter for each position, most important first, and which
# PlayerWeekStat field they live on. The first one drives the headline
# trend label; the rest ride along for context.
POSITION_TREND_STATS: dict[str, list[tuple[str, str]]] = {
    "QB": [("pass_attempts", "raw_stats_actual"), ("pass_yards", "raw_stats_actual")],
    "RB": [
        ("carries", "raw_stats_actual"),
        ("targets", "raw_stats_actual"),
        ("snap_pct", "advanced_stats"),
    ],
    "WR": [
        ("targets", "raw_stats_actual"),
        ("target_share", "advanced_stats"),
        ("receptions", "raw_stats_actual"),
        ("snap_pct", "advanced_stats"),
    ],
    "TE": [
        ("targets", "raw_stats_actual"),
        ("target_share", "advanced_stats"),
        ("receptions", "raw_stats_actual"),
        ("snap_pct", "advanced_stats"),
    ],
}

STAT_LABELS: dict[str, str] = {
    "pass_attempts": "Pass Att",
    "pass_completions": "Comp",
    "pass_yards": "Pass Yds",
    "carries": "Carries",
    "rush_yards": "Rush Yds",
    "targets": "Targets",
    "receptions": "Rec",
    "rec_yards": "Rec Yds",
    "target_share": "Tgt Share %",
    "air_yards_share": "Air Yds Share %",
    "wopr": "WOPR",
    "snap_pct": "Snap %",
}

UP_THRESHOLD = 1.15
DOWN_THRESHOLD = 0.85


def _trend_label(values: list[float]) -> str | None:
    if len(values) < 2:
        return None
    mid = max(1, len(values) // 2)
    first_avg = sum(values[:mid]) / mid
    second_avg = sum(values[mid:]) / max(1, len(values) - mid)
    if first_avg == 0:
        return "up" if second_avg > 0 else None
    ratio = second_avg / first_avg
    if ratio > UP_THRESHOLD:
        return "up"
    if ratio < DOWN_THRESHOLD:
        return "down"
    return "flat"


def get_player_trend(
    db: Session, league_id: int, espn_player_id: int, position: str, weeks_back: int = 4
) -> dict | None:
    stat_keys = POSITION_TREND_STATS.get(position)
    if not stat_keys:
        return None

    # Over-fetch and filter in Python for "this week was actually played"
    # rather than filtering on actual_points in SQL: a week can have real
    # data (raw counting stats from ESPN, or advanced stats from nflverse)
    # without actual_points necessarily being set, and vice versa a bye/
    # future week can exist as a row with neither populated.
    candidates = (
        db.query(PlayerWeekStat)
        .filter(PlayerWeekStat.league_id == league_id, PlayerWeekStat.espn_player_id == espn_player_id)
        .order_by(PlayerWeekStat.week.desc())
        .limit(weeks_back + 4)
        .all()
    )
    played = [row for row in candidates if row.raw_stats_actual or row.advanced_stats]
    rows = list(reversed(played[:weeks_back]))  # chronological order
    if not rows:
        return None

    stats: dict[str, dict] = {}
    for key, field in stat_keys:
        values = [getattr(row, field).get(key) for row in rows]
        values = [v for v in values if v is not None]
        if not values:
            continue
        stats[key] = {
            "label": STAT_LABELS.get(key, key),
            "recent": values,
            "trend": _trend_label(values),
        }

    if not stats:
        return None
    return {"weeks_counted": len(rows), "stats": stats}
