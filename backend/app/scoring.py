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


def _find_stat_entry(player_json: dict, week: int, source_id: int) -> dict | None:
    for entry in player_json.get("stats", []) or []:
        if (
            entry.get("statSourceId") == source_id
            and entry.get("scoringPeriodId") == week
            and entry.get("statSplitTypeId") == STAT_SPLIT_WEEKLY
        ):
            return entry
    return None


def player_points_for_week(player_json: dict, week: int) -> tuple[float | None, float | None]:
    """Return (projected_points, actual_points) for a player in a given week."""
    projected_entry = _find_stat_entry(player_json, week, STAT_SOURCE_PROJECTED)
    actual_entry = _find_stat_entry(player_json, week, STAT_SOURCE_ACTUAL)
    projected = projected_entry.get("appliedTotal") if projected_entry else None
    actual = actual_entry.get("appliedTotal") if actual_entry else None
    return projected, actual


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
