"""FantasyPros expert consensus rankings (ECR) — the "wisdom of the
crowd" signal neither ESPN nor nflverse provide (they're all stats-based;
this is a poll of real fantasy analysts).

Requires FANTASYPROS_API_KEY (config.settings.fantasypros_api_key). A free
API key hard-caps every query at the top 10 results regardless of
filters — confirmed against the live API, not documented anywhere — so
this is only useful for elite/startable players, not full-roster or
waiver-wire coverage. See README for the scoped feature this powers.

Everything here is best-effort like the other external data sources: no
key, or any request failure, returns an empty result rather than raising.
"""

from __future__ import annotations

import datetime
import json
import os
import time

import httpx

from app.config import settings

BASE_URL = "https://api.fantasypros.com/public/v2/json/nfl/{season}/{endpoint}"
RANKING_POSITIONS = ["QB", "RB", "WR", "TE", "K", "DST"]

CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "fantasypros_cache")
CACHE_MAX_AGE_SECONDS = 6 * 60 * 60  # 6 hours — ECR moves slowly day to day


def infer_scoring_format(scoring_rules: list[dict]) -> str:
    """Map a league's synced scoring rules to FantasyPros' STD/HALF/PPR
    scoring param, based on the per-reception point value."""
    for rule in scoring_rules:
        if rule.get("stat_name") == "Receiving Receptions":
            points = rule.get("points") or 0
            if points >= 1:
                return "PPR"
            if points >= 0.5:
                return "HALF"
            break
    return "STD"


def _cache_path(cache_key: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{cache_key}.json")


def _cached_get(endpoint: str, params: dict, cache_key: str) -> dict | None:
    if not settings.fantasypros_api_key:
        return None

    path = _cache_path(cache_key)
    if os.path.exists(path) and (time.time() - os.path.getmtime(path)) < CACHE_MAX_AGE_SECONDS:
        try:
            with open(path) as f:
                return json.load(f)
        except (OSError, ValueError):
            pass  # fall through and re-fetch

    url = BASE_URL.format(season=params.pop("season"), endpoint=endpoint)
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(url, params=params, headers={"x-api-key": settings.fantasypros_api_key})
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return None

    tmp_path = path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(data, f)
    os.replace(tmp_path, path)
    return data


def _trim_player(raw: dict) -> dict:
    def _num(key):
        value = raw.get(key)
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    return {
        "fantasypros_id": raw.get("player_id"),
        "name": raw.get("player_name"),
        "team": raw.get("player_team_id"),
        "position": raw.get("player_position_id"),
        "pos_rank": raw.get("pos_rank"),
        "ecr_rank": raw.get("rank_ecr"),
        "ecr_delta": raw.get("player_ecr_delta"),
        "rank_min": _num("rank_min"),
        "rank_max": _num("rank_max"),
        "rank_std": _num("rank_std"),
        "page_url": raw.get("player_page_url"),
    }


def fetch_consensus_rankings(season: int, position: str, ranking_type: str, scoring: str, week: int | None = None) -> list[dict]:
    """One query against FantasyPros' consensus-rankings endpoint.
    `ranking_type` is "ROS" or "weekly". `position` is "ALL" or one of
    RANKING_POSITIONS. Returns [] if unavailable for any reason (no key,
    request failure, or an empty/malformed response)."""
    params = {"season": season, "type": ranking_type, "position": position, "scoring": scoring}
    if week is not None:
        params["week"] = week
    cache_key = f"rankings_{season}_{ranking_type}_{position}_{scoring}_{week or 0}"
    data = _cached_get("consensus-rankings", params, cache_key)
    if not data:
        return []
    return [_trim_player(p) for p in data.get("players", [])]


def fetch_expert_rankings_bundle(
    season: int, week: int, scoring: str, crosswalk: dict[int, dict[str, str]]
) -> dict:
    """Top-10 overall + top-10 per position, for both rest-of-season and
    this week, with espn_player_id filled in wherever the dynastyprocess
    crosswalk has a match (defenses don't — they're not in that file, so
    their espn_player_id stays None; the reference panel still shows them
    by team name, they just can't be joined onto our Player rows).
    """
    if not settings.fantasypros_api_key:
        return {}

    fpid_to_espn_id = {
        ids["fantasypros_id"]: espn_id
        for espn_id, ids in crosswalk.items()
        if ids.get("fantasypros_id")
    }

    def with_espn_ids(players: list[dict]) -> list[dict]:
        for p in players:
            fpid = str(p["fantasypros_id"]) if p["fantasypros_id"] is not None else None
            p["espn_player_id"] = fpid_to_espn_id.get(fpid)
        return players

    def fetch_all_positions(ranking_type: str, week_param: int | None) -> dict:
        bundle = {"overall": with_espn_ids(fetch_consensus_rankings(season, "ALL", ranking_type, scoring, week_param))}
        for position in RANKING_POSITIONS:
            bundle[position] = with_espn_ids(fetch_consensus_rankings(season, position, ranking_type, scoring, week_param))
        return bundle

    ros = fetch_all_positions("ROS", None)
    weekly = fetch_all_positions("weekly", week)

    if not ros["overall"] and not weekly["overall"]:
        return {}  # FantasyPros unreachable this sync — leave any prior data alone by returning nothing new

    return {
        "scoring": scoring,
        "week": week,
        "updated_at": datetime.datetime.utcnow().isoformat(),
        "ros": ros,
        "weekly": weekly,
    }


def get_expert_context(league_expert_rankings: dict, espn_player_id: int) -> dict | None:
    """Look up a single player's expert-consensus context (for Trade
    Grader enrichment) from a League.expert_rankings bundle — present
    only if that player happens to be in one of the top-10 lists."""
    if not league_expert_rankings:
        return None
    ros = league_expert_rankings.get("ros", {})
    for players in ros.values():
        for p in players:
            if p.get("espn_player_id") == espn_player_id:
                return p
    return None
