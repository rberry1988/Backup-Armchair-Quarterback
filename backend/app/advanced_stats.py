"""Turns raw nflverse rows into per-player weekly advanced stats and real
team points-allowed-by-position, joined to our ESPN-keyed data via the
dynastyprocess player-id crosswalk (espn_id <-> gsis_id/pfr_id).
"""

from __future__ import annotations

from collections import defaultdict

SKILL_POSITIONS = {"QB", "RB", "WR", "TE"}


def index_weekly_by_gsis(weekly_rows: list[dict]) -> dict[str, dict[int, dict]]:
    index: dict[str, dict[int, dict]] = defaultdict(dict)
    for row in weekly_rows:
        gsis_id = row.get("player_id")
        week = row.get("week")
        if not gsis_id or week is None:
            continue
        try:
            week_int = int(week)
        except ValueError:
            continue
        index[gsis_id][week_int] = row
    return index


def index_snaps_by_pfr(snap_rows: list[dict]) -> dict[str, dict[int, float]]:
    index: dict[str, dict[int, float]] = defaultdict(dict)
    for row in snap_rows:
        pfr_id = row.get("pfr_player_id")
        week = row.get("week")
        offense_pct = row.get("offense_pct")
        if not pfr_id or week is None or offense_pct is None:
            continue
        try:
            week_int = int(week)
        except ValueError:
            continue
        index[pfr_id][week_int] = offense_pct
    return index


def get_advanced_stats_for_player(
    espn_id: int,
    crosswalk: dict[int, dict[str, str]],
    gsis_index: dict[str, dict[int, dict]],
    pfr_index: dict[str, dict[int, float]],
) -> dict[int, dict]:
    """Return {week: {target_share, air_yards_share, wopr, air_yards,
    yards_after_catch, snap_pct}} for every week we have nflverse data on
    this player, using only whichever fields are present."""
    ids = crosswalk.get(espn_id)
    if not ids:
        return {}

    weeks: dict[int, dict] = {}
    gsis_id = ids.get("gsis_id")
    if gsis_id:
        for week, row in gsis_index.get(gsis_id, {}).items():
            stats = {}
            if row.get("target_share") is not None:
                stats["target_share"] = round(row["target_share"] * 100, 1)
            if row.get("air_yards_share") is not None:
                stats["air_yards_share"] = round(row["air_yards_share"] * 100, 1)
            if row.get("wopr") is not None:
                stats["wopr"] = round(row["wopr"], 2)
            if row.get("receiving_air_yards") is not None:
                stats["air_yards"] = row["receiving_air_yards"]
            if row.get("receiving_yards_after_catch") is not None:
                stats["yards_after_catch"] = row["receiving_yards_after_catch"]
            if stats:
                weeks[week] = stats

    pfr_id = ids.get("pfr_id")
    if pfr_id:
        for week, offense_pct in pfr_index.get(pfr_id, {}).items():
            weeks.setdefault(week, {})["snap_pct"] = round(offense_pct * 100, 1)

    return weeks


def compute_points_allowed_by_position(weekly_rows: list[dict], through_week: int) -> dict[str, dict[str, float]]:
    """Average PPR fantasy points each team has allowed per game, by
    position, using only weeks played so far this season. Real
    points-allowed data (unlike the D/ST-projection proxy this replaces
    when unavailable) — the standard "matchup vs. position" signal fantasy
    sites use.
    """
    totals: dict[tuple[str, str], float] = defaultdict(float)
    games: dict[tuple[str, str], set[int]] = defaultdict(set)

    for row in weekly_rows:
        position = row.get("position")
        if position not in SKILL_POSITIONS:
            continue
        opponent = row.get("opponent_team")
        week = row.get("week")
        points = row.get("fantasy_points_ppr")
        if not opponent or week is None or points is None:
            continue
        try:
            week_int = int(week)
        except ValueError:
            continue
        if week_int > through_week:
            continue
        key = (opponent, position)
        totals[key] += points
        games[key].add(week_int)

    result: dict[str, dict[str, float]] = defaultdict(dict)
    for (team, position), total in totals.items():
        game_count = len(games[(team, position)])
        if game_count > 0:
            result[team][position] = round(total / game_count, 1)
    return dict(result)
