"""Helpers for reading ESPN's per-league scoring settings and player stats.

ESPN computes `appliedTotal` on each player stat entry using the scoring
rules of whichever league the request was scoped to, so we don't need to
re-implement their scoring math from raw stat counts. We do still sync the
raw scoringItems (statId -> points-per-unit) so the league's rules can be
shown in the UI and so the ruleset that drove a projection is transparent.
"""

from __future__ import annotations

from typing import Any

from app.espn_constants import STAT_ID_MAP

STAT_SOURCE_PROJECTED = 1
STAT_SOURCE_ACTUAL = 0
STAT_SPLIT_WEEKLY = 1

# Raw counting stats worth tracking week-to-week as usage/opportunity
# signals (targets, carries, etc.) rather than fantasy-point totals — these
# move before points do and are what "trending up/down" usually means.
TRACKED_RAW_STAT_IDS: dict[int, str] = {
    0: "pass_attempts",
    1: "pass_completions",
    3: "pass_yards",
    24: "carries",
    25: "rush_yards",
    42: "rec_yards",
    53: "receptions",
    58: "targets",
}


def build_scoring_rules(league_json: dict) -> list[dict]:
    """Return a readable list of {stat, points} from the league's settings."""
    settings = league_json.get("settings", {})
    scoring_settings = settings.get("scoringSettings", {})
    items = scoring_settings.get("scoringItems", [])
    is_ppr_flag = scoring_settings.get("scoringType")
    rules = []
    for item in items:
        stat_id = item.get("statId")
        points = item.get("points")
        if points in (None, 0):
            continue
        rules.append(
            {
                "stat_id": stat_id,
                "stat_name": STAT_ID_MAP.get(stat_id, f"Stat {stat_id}"),
                "points": points,
            }
        )
    rules.sort(key=lambda r: r["stat_name"])
    return rules


def extract_raw_stats(entry: dict) -> dict[str, float]:
    """Pull the tracked raw counting stats (targets, carries, ...) out of a
    single stats-array entry's raw `stats` dict (statId(str) -> value)."""
    raw = entry.get("stats") or {}
    result: dict[str, float] = {}
    for stat_id, key in TRACKED_RAW_STAT_IDS.items():
        value = raw.get(str(stat_id))
        if value is not None:
            result[key] = value
    return result


def all_weekly_data(player_json: dict) -> dict[int, dict]:
    """Return {week: {"projected", "actual", "raw_stats_actual",
    "raw_stats_projected"}} for every week ESPN has a stat entry for on this
    player (past weeks played + near-term projections). Used to build
    season history in one pass instead of one network round-trip per week.
    """
    weeks: dict[int, dict] = {}
    for entry in player_json.get("stats", []) or []:
        if entry.get("statSplitTypeId") != STAT_SPLIT_WEEKLY:
            continue
        week = entry.get("scoringPeriodId")
        source = entry.get("statSourceId")
        if week is None or source not in (STAT_SOURCE_PROJECTED, STAT_SOURCE_ACTUAL):
            continue
        bucket = weeks.setdefault(
            week, {"projected": None, "actual": None, "raw_stats_actual": {}, "raw_stats_projected": {}}
        )
        applied = entry.get("appliedTotal")
        if source == STAT_SOURCE_PROJECTED:
            bucket["projected"] = applied
            bucket["raw_stats_projected"] = extract_raw_stats(entry)
        else:
            bucket["actual"] = applied
            bucket["raw_stats_actual"] = extract_raw_stats(entry)
    return weeks


def all_weekly_points(player_json: dict) -> dict[int, dict[str, float | None]]:
    """Return {week: {"projected": ..., "actual": ...}} — same as
    all_weekly_data() but without the raw stat breakdowns, for callers that
    only need point totals."""
    return {
        week: {"projected": d["projected"], "actual": d["actual"]} for week, d in all_weekly_data(player_json).items()
    }


def player_points_for_week(player_json: dict, week: int) -> tuple[float | None, float | None]:
    """Return (projected_points, actual_points) for a player in a given week."""
    bucket = all_weekly_points(player_json).get(week, {})
    return bucket.get("projected"), bucket.get("actual")


def extract_player_core(player_json: dict) -> dict[str, Any]:
    ownership = player_json.get("ownership", {}) or {}
    return {
        "espn_id": player_json.get("id"),
        "full_name": player_json.get("fullName"),
        "default_position_id": player_json.get("defaultPositionId"),
        "pro_team_id": player_json.get("proTeamId"),
        "injury_status": player_json.get("injuryStatus", "ACTIVE"),
        "eligible_slots": player_json.get("eligibleSlots", []),
        "percent_owned": ownership.get("percentOwned", 0.0),
        "percent_started": ownership.get("percentStarted", 0.0),
    }
