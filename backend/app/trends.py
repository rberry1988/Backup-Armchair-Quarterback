"""Usage-trend tracking: targets, carries, and similar opportunity stats
move before fantasy points do, so surfacing the last few weeks' raw counts
(and whether they're rising or falling) is often a better early signal than
points alone — this is what waiver-wire "buy low / sell high" calls are
usually based on.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import PlayerWeekStat

# Which raw stats matter for each position, most important first. The
# first one drives the headline trend label; the rest ride along for
# context (e.g. a receiving back's targets alongside carries).
POSITION_TREND_STATS: dict[str, list[str]] = {
    "QB": ["pass_attempts", "pass_yards"],
    "RB": ["carries", "targets"],
    "WR": ["targets", "receptions"],
    "TE": ["targets", "receptions"],
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

    rows = (
        db.query(PlayerWeekStat)
        .filter(
            PlayerWeekStat.league_id == league_id,
            PlayerWeekStat.espn_player_id == espn_player_id,
            PlayerWeekStat.actual_points.isnot(None),
        )
        .order_by(PlayerWeekStat.week.desc())
        .limit(weeks_back)
        .all()
    )
    if not rows:
        return None
    rows = list(reversed(rows))  # chronological order

    stats: dict[str, dict] = {}
    for key in stat_keys:
        values = [row.raw_stats_actual.get(key) for row in rows]
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
