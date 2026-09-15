"""FantasyCalc trade values — a market-consensus player value (derived from
real user-submitted trades on their site) for exactly the "is this trade
fair" question Trade Grader answers with its own points-based methodology.
Free, public, no API key needed: https://fantasycalc.com/api-docs.

Values are scaled to a league's actual format (team count, PPR, QB slots),
so different leagues get different numbers for the same player. Everything
here is best-effort like the other external data sources: any failure
returns an empty result rather than raising, and the existing points-based
trade grade never depends on this succeeding — see get_trade_value().
"""

from __future__ import annotations

import json
import os
import tempfile
import time

import httpx

BASE_URL = "https://api.fantasycalc.com/values/current"

CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "fantasycalc_cache")
CACHE_MAX_AGE_SECONDS = 6 * 60 * 60  # 6 hours — matches the other market-data caches


def _cache_path(cache_key: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{cache_key}.json")


def fetch_player_values(num_teams: int, ppr: float, num_qbs: int = 1, is_dynasty: bool = False) -> dict[int, dict]:
    """{espn_player_id: {"value": int, "position_rank": int, "overall_rank":
    int, "tier": int | None, "trend_30_day": int}} for every player
    FantasyCalc has a value for, scaled to this league's format. Returns {}
    on any failure (no network, malformed response, ...) rather than
    raising — enrichment only, never load-bearing for the trade grade.
    """
    cache_key = f"values_{'dynasty' if is_dynasty else 'redraft'}_{num_teams}t_{num_qbs}qb_{ppr}ppr"
    path = _cache_path(cache_key)
    if os.path.exists(path) and (time.time() - os.path.getmtime(path)) < CACHE_MAX_AGE_SECONDS:
        try:
            with open(path) as f:
                return {int(k): v for k, v in json.load(f).items()}
        except (OSError, ValueError):
            pass  # fall through and re-fetch

    params = {
        "isDynasty": "true" if is_dynasty else "false",
        "numQbs": num_qbs,
        "numTeams": num_teams,
        "ppr": ppr,
    }
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(BASE_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return {}

    result: dict[int, dict] = {}
    for entry in data:
        player = entry.get("player") or {}
        espn_id = player.get("espnId")
        if not espn_id:
            continue  # no ESPN id to join on (rare, mostly deep/inactive players)
        try:
            espn_id = int(espn_id)
        except (TypeError, ValueError):
            continue
        result[espn_id] = {
            "value": entry.get("value"),
            "position_rank": entry.get("positionRank"),
            "overall_rank": entry.get("overallRank"),
            "tier": entry.get("maybeTier"),
            "trend_30_day": entry.get("trend30Day"),
        }

    # A unique per-write temp name (not a fixed "<path>.tmp") so two
    # concurrent syncs refreshing the same cache entry can't interleave
    # writes to the same staging path before either renames it into place.
    fd, tmp_path = tempfile.mkstemp(dir=CACHE_DIR, prefix=os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(result, f)
        os.replace(tmp_path, path)
    except BaseException:
        os.unlink(tmp_path)
        raise
    return result


def ppr_from_scoring_rules(scoring_rules: list[dict]) -> float:
    """FantasyCalc wants a numeric PPR value (0, 0.5, or 1), unlike
    FantasyPros' STD/HALF/PPR label — read the same "Receiving Receptions"
    rule fantasypros_client.infer_scoring_format() uses, snapped to the
    nearest value FantasyCalc's API actually supports."""
    for rule in scoring_rules:
        if rule.get("stat_name") == "Receiving Receptions":
            points = rule.get("points") or 0
            if points >= 0.75:
                return 1.0
            if points >= 0.25:
                return 0.5
            break
    return 0.0


def num_qbs_from_roster_slots(roster_slot_counts: dict) -> int:
    """2 for a superflex/2-QB league (an "OP" slot, or more than one
    dedicated QB slot), else the standard 1 — meaningfully changes QB
    values, which FantasyCalc scales per format."""
    if roster_slot_counts.get("OP", 0) > 0:
        return 2
    if roster_slot_counts.get("QB", 0) > 1:
        return 2
    return 1


def get_trade_value(fantasycalc_values: dict, espn_player_id: int) -> dict | None:
    """Look up a single player's value from a League.fantasycalc_values
    bundle (JSON-keyed by string espn_player_id) — None if FantasyCalc
    doesn't carry that player (very deep bench, inactive, etc.)."""
    if not fantasycalc_values:
        return None
    return fantasycalc_values.get(str(espn_player_id))
