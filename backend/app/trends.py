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

from collections import defaultdict

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


def _trend_from_rows(rows: list[PlayerWeekStat], position: str, weeks_back: int) -> dict | None:
    stat_keys = POSITION_TREND_STATS.get(position)
    if not stat_keys:
        return None

    # rows arrive newest-first; keep only weeks that were actually played
    # (real data in either source — actual_points isn't a reliable enough
    # signal on its own, see get_player_trends' docstring) and take the
    # most recent `weeks_back` of those, oldest to newest.
    played = [row for row in rows if row.raw_stats_actual or row.advanced_stats]
    played_recent = list(reversed(played[:weeks_back]))
    if not played_recent:
        return None

    stats: dict[str, dict] = {}
    for key, field in stat_keys:
        values = [getattr(row, field).get(key) for row in played_recent]
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
    return {"weeks_counted": len(played_recent), "stats": stats}


def get_player_trends(
    db: Session, league_id: int, players: list[tuple[int, str]], weeks_back: int = 4
) -> dict[int, dict | None]:
    """Batched form of get_player_trend() — one query for many players
    instead of one query each, for pages that render a whole roster or
    waiver list at once. `players` is a list of (espn_player_id, position).

    A week can have real data (raw counting stats from ESPN, or advanced
    stats from nflverse) without actual_points necessarily being set, and
    vice versa a bye/future week can exist as a row with neither populated
    — so "was this week played" is decided by row content, not
    actual_points, hence the over-fetch-and-filter-in-Python approach
    below rather than a SQL-level per-player LIMIT.
    """
    espn_ids = [pid for pid, _ in players]
    if not espn_ids:
        return {}

    rows_by_player: dict[int, list[PlayerWeekStat]] = defaultdict(list)
    all_rows = (
        db.query(PlayerWeekStat)
        .filter(PlayerWeekStat.league_id == league_id, PlayerWeekStat.espn_player_id.in_(espn_ids))
        .order_by(PlayerWeekStat.espn_player_id, PlayerWeekStat.week.desc())
        .all()
    )
    for row in all_rows:
        rows_by_player[row.espn_player_id].append(row)

    return {
        espn_id: _trend_from_rows(rows_by_player.get(espn_id, []), position, weeks_back)
        for espn_id, position in players
    }


def get_player_trend(
    db: Session, league_id: int, espn_player_id: int, position: str, weeks_back: int = 4
) -> dict | None:
    """Single-player convenience wrapper around get_player_trends()."""
    return get_player_trends(db, league_id, [(espn_player_id, position)], weeks_back)[espn_player_id]
