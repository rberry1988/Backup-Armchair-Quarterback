"""FantasyPros data: expert consensus rankings (ECR) — the "wisdom of the
crowd" signal neither ESPN nor nflverse provide (they're all stats-based;
this is a poll of real fantasy analysts) — and full-league injury reports
with practice-participation history and a plain-English analyst comment,
which ESPN's sync only gives us as a single status string.

Requires an API key (backend/.env's FANTASYPROS_API_KEY, or one saved
from the Admin tab — see app/app_settings.py, which resolves the
effective key callers pass in here). A free API key hard-caps every
consensus-rankings query at the top 10 results regardless of filters —
confirmed against the live API, not documented anywhere — so that
endpoint is only useful for elite/startable players, not full-roster or
waiver-wire coverage. The injuries endpoint has no such cap (confirmed
against the live API/spec), so it covers every rostered player. See
README for the scoped feature this powers.

Everything here is best-effort like the other external data sources: no
key, or any request failure, returns an empty result rather than raising.
"""

from __future__ import annotations

import datetime
import json
import os
import tempfile
import time

import httpx

BASE_URL = "https://api.fantasypros.com/public/v2/json/nfl/{season}/{endpoint}"
INJURIES_URL = "https://api.fantasypros.com/public/v2/json/nfl/injuries"
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


def _cached_get_url(url: str, params: dict, cache_key: str, api_key: str | None) -> dict | None:
    if not api_key:
        return None

    path = _cache_path(cache_key)
    if os.path.exists(path) and (time.time() - os.path.getmtime(path)) < CACHE_MAX_AGE_SECONDS:
        try:
            with open(path) as f:
                return json.load(f)
        except (OSError, ValueError):
            pass  # fall through and re-fetch

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(url, params=params, headers={"x-api-key": api_key})
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return None

    # A unique per-write temp name (not a fixed "<path>.tmp") so two
    # concurrent syncs refreshing the same cache entry can't interleave
    # writes to the same staging path before either renames it into place.
    fd, tmp_path = tempfile.mkstemp(dir=CACHE_DIR, prefix=os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp_path, path)
    except BaseException:
        os.unlink(tmp_path)
        raise
    return data


def _cached_get(endpoint: str, params: dict, cache_key: str, api_key: str | None) -> dict | None:
    url = BASE_URL.format(season=params.pop("season"), endpoint=endpoint)
    return _cached_get_url(url, params, cache_key, api_key)


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


def fetch_consensus_rankings(
    season: int, position: str, ranking_type: str, scoring: str, api_key: str | None, week: int | None = None
) -> list[dict]:
    """One query against FantasyPros' consensus-rankings endpoint.
    `ranking_type` is "ROS" or "weekly". `position` is "ALL" or one of
    RANKING_POSITIONS. Returns [] if unavailable for any reason (no key,
    request failure, or an empty/malformed response)."""
    params = {"season": season, "type": ranking_type, "position": position, "scoring": scoring}
    if week is not None:
        params["week"] = week
    cache_key = f"rankings_{season}_{ranking_type}_{position}_{scoring}_{week or 0}"
    data = _cached_get("consensus-rankings", params, cache_key, api_key)
    if not data:
        return []
    return [_trim_player(p) for p in data.get("players", [])]


def fetch_expert_rankings_bundle(
    season: int, week: int, scoring: str, crosswalk: dict[int, dict[str, str]], api_key: str | None
) -> dict:
    """Top-10 overall + top-10 per position, for both rest-of-season and
    this week, with espn_player_id filled in wherever the dynastyprocess
    crosswalk has a match (defenses don't — they're not in that file, so
    their espn_player_id stays None; the reference panel still shows them
    by team name, they just can't be joined onto our Player rows).
    """
    if not api_key:
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
        bundle = {
            "overall": with_espn_ids(fetch_consensus_rankings(season, "ALL", ranking_type, scoring, api_key, week_param))
        }
        for position in RANKING_POSITIONS:
            bundle[position] = with_espn_ids(
                fetch_consensus_rankings(season, position, ranking_type, scoring, api_key, week_param)
            )
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


def _trim_injury(raw: dict) -> dict:
    def _num(key):
        value = raw.get(key)
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    return {
        "fantasypros_id": raw.get("player_id"),
        "status": raw.get("status"),
        "injury_type": raw.get("practice_report_injury_type"),
        "comment": raw.get("comment"),
        "probability_of_playing": _num("probability_of_playing"),
        # Practice participation for the week so far, oldest to newest —
        # "Limit" then "Full" reads very differently than "Full" then "DNP".
        "practice_report": [p for p in (raw.get("practice_1"), raw.get("practice_2"), raw.get("practice_3")) if p],
        "updated_at": raw.get("injury_update_date"),
    }


def fetch_injuries(season: int, week: int, api_key: str | None) -> list[dict]:
    """Full NFL injury report for the week — unlike consensus-rankings,
    not capped at the top 10 by a free key, so this covers every rostered
    player rather than just elite/startable ones.
    include_probabilities=true also surfaces practice-report-only players
    who don't have an official game status yet. Returns [] on any failure
    (no key, request failure, malformed response)."""
    params = {"year": season, "week": week, "include_probabilities": "true"}
    cache_key = f"injuries_{season}_{week}"
    data = _cached_get_url(INJURIES_URL, params, cache_key, api_key)
    if not data:
        return []
    return [_trim_injury(p) for p in data.get("injuries", [])]


def fetch_injury_context(
    season: int, week: int, crosswalk: dict[int, dict[str, str]], api_key: str | None
) -> dict[int, dict]:
    """{espn_player_id: injury dict} for every player FantasyPros has an
    injury/practice-report entry for this week, joined via the same
    dynastyprocess crosswalk used for expert rankings. Best-effort: {} on
    any failure, or if nothing in the report has a crosswalk match."""
    injuries = fetch_injuries(season, week, api_key)
    if not injuries:
        return {}

    fpid_to_espn_id = {
        ids["fantasypros_id"]: espn_id for espn_id, ids in crosswalk.items() if ids.get("fantasypros_id")
    }

    result: dict[int, dict] = {}
    for injury in injuries:
        fpid = str(injury["fantasypros_id"]) if injury["fantasypros_id"] is not None else None
        espn_id = fpid_to_espn_id.get(fpid)
        if espn_id is not None:
            result[espn_id] = injury
    return result


def get_injury_context(league_fantasypros_injuries: dict, espn_player_id: int) -> dict | None:
    """Look up a single player's FantasyPros injury context from a
    League.fantasypros_injuries bundle (JSON-keyed by string
    espn_player_id) — None if FantasyPros has no injury/practice-report
    entry for them (i.e. they're not banged up this week)."""
    if not league_fantasypros_injuries:
        return None
    return league_fantasypros_injuries.get(str(espn_player_id))
