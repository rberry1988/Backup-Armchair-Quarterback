"""Turns raw nflverse rows into per-player weekly advanced stats and real
team points-allowed-by-position, joined to our ESPN-keyed data via the
dynastyprocess player-id crosswalk (espn_id <-> gsis_id/pfr_id).
"""

from __future__ import annotations

from collections import defaultdict

from app.espn_constants import normalize_team_abbr

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
        key = (normalize_team_abbr(opponent), position)
        totals[key] += points
        games[key].add(week_int)

    result: dict[str, dict[str, float]] = defaultdict(dict)
    for (team, position), total in totals.items():
        game_count = len(games[(team, position)])
        if game_count > 0:
            result[team][position] = round(total / game_count, 1)
    return dict(result)


# What a defense actually gives up to each position, in the units that
# position is judged in. Fantasy points allowed is a fine ranking signal but
# a poor explanation — "allows 24.6 points to WRs" is circular if you're
# trying to decide whether to trust the projection those points came from.
# Real yardage is the underlying thing.
#
# (field the yards come from, field the TDs come from, short label)
POSITION_METRICS: dict[str, tuple[str, str, str]] = {
    "QB": ("passing_yards", "passing_tds", "pass yds"),
    "RB": ("rushing_yards", "rushing_tds", "rush yds"),
    # A WR's or TE's share of what a defense gives up through the air —
    # narrower and more useful than the team's total passing yards allowed,
    # which is already covered by the QB row above.
    "WR": ("receiving_yards", "receiving_tds", "rec yds"),
    "TE": ("receiving_yards", "receiving_tds", "rec yds"),
}


def _as_float(value) -> float | None:
    """nflverse CSVs carry empty strings and "NA" for absent values."""
    if value is None or value == "" or value == "NA":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def compute_defense_vs_position(weekly_rows: list[dict], through_week: int) -> dict[str, dict[str, dict]]:
    """Per game, what each team's defense has allowed to each position:

        {"BUF": {"RB": {"yards": 88.4, "tds": 0.4, "points": 17.2,
                        "metric": "rush yds", "games": 3}}}

    Yardage is position-appropriate (rushing for RBs, receiving for
    WRs/TEs, passing for QBs — see POSITION_METRICS); `points` is the same
    PPR figure compute_points_allowed_by_position() produces, kept
    alongside so positions without a meaningful yardage stat (K, D/ST)
    still have something to rank on.

    Weeks beyond `through_week` are ignored so a mid-season sync isn't
    polluted by rows from games that haven't been played in this league's
    frame of reference.
    """
    yards: dict[tuple[str, str], float] = defaultdict(float)
    tds: dict[tuple[str, str], float] = defaultdict(float)
    points: dict[tuple[str, str], float] = defaultdict(float)
    # Two denominators, deliberately. A week with no usable yardage figure
    # must not divide the yardage total — that would book it as a shutout
    # and flatter the defense — but it can still count toward the points
    # average if the points came through. They're the same set in practice;
    # keeping them apart is what stops a gap in one field quietly
    # corrupting the other.
    yard_games: dict[tuple[str, str], set[int]] = defaultdict(set)
    point_games: dict[tuple[str, str], set[int]] = defaultdict(set)

    for row in weekly_rows:
        position = row.get("position")
        if position not in SKILL_POSITIONS:
            continue
        opponent = row.get("opponent_team")
        week = row.get("week")
        if not opponent or week is None:
            continue
        try:
            week_int = int(week)
        except (TypeError, ValueError):
            continue
        if week_int > through_week:
            continue

        yards_field, tds_field, _ = POSITION_METRICS[position]
        row_yards = _as_float(row.get(yards_field))
        row_tds = _as_float(row.get(tds_field))
        row_points = _as_float(row.get("fantasy_points_ppr"))
        if row_yards is None and row_points is None:
            continue

        key = (normalize_team_abbr(opponent), position)
        if row_yards is not None:
            yards[key] += row_yards
            tds[key] += row_tds or 0.0
            # A genuine 0-yard week counts: holding a position scoreless is
            # exactly what a tough defense does, and dropping those weeks
            # would erase the evidence for it.
            yard_games[key].add(week_int)
        if row_points is not None:
            points[key] += row_points
            point_games[key].add(week_int)

    result: dict[str, dict[str, dict]] = defaultdict(dict)
    for key in set(yard_games) | set(point_games):
        team, position = key
        yard_count = len(yard_games[key])
        point_count = len(point_games[key])
        entry: dict = {
            "metric": POSITION_METRICS[position][2],
            # How many games the yardage figure rests on, so a rating built
            # on one week can be told apart from one built on a season.
            "games": yard_count or point_count,
        }
        if yard_count:
            entry["yards"] = round(yards[key] / yard_count, 1)
            entry["tds"] = round(tds[key] / yard_count, 2)
        if point_count:
            entry["points"] = round(points[key] / point_count, 1)
        result[team][position] = entry
    return dict(result)
