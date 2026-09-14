"""Thin wrapper around ESPN's undocumented public fantasy football API.

Only the read-only endpoints needed for a public league are used:
no login/cookie flow is implemented. If ESPN ever requires cookies for a
league that used to be public, set ESPN_S2 / ESPN_SWID in .env and they'll
be sent automatically (see `_cookies`).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx

from app.config import settings

BASE_URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}/segments/0/leagues/{league_id}"

# ESPN's public (separate, non-fantasy) sports scoreboard API. Confirmed to
# use the same numeric NFL team ids as the fantasy API's proTeamId (e.g.
# Green Bay is 9 in both), so no separate id-mapping table is needed.
SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"

# Regular season only — weeks 1-18. Bye weeks and the multi-week outlook
# both need the whole season, not just the current week.
REGULAR_SEASON_WEEKS = 18

SCHEDULE_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "schedule_cache")
# The NFL regular-season schedule is fixed once published, so this only
# needs re-fetching for flex-scheduling tweaks, not within a day.
SCHEDULE_CACHE_MAX_AGE_SECONDS = 24 * 60 * 60


def _parse_scoreboard(data: dict) -> dict[int, dict]:
    schedule: dict[int, dict] = {}
    for event in data.get("events", []):
        competitors = (event.get("competitions") or [{}])[0].get("competitors", [])
        if len(competitors) != 2:
            continue
        a, b = competitors
        try:
            id_a, id_b = int(a["team"]["id"]), int(b["team"]["id"])
        except (KeyError, TypeError, ValueError):
            continue
        abbr_a, abbr_b = a["team"].get("abbreviation", ""), b["team"].get("abbreviation", "")
        schedule[id_a] = {"abbreviation": abbr_a, "opponent_id": id_b, "opponent_abbreviation": abbr_b}
        schedule[id_b] = {"abbreviation": abbr_b, "opponent_id": id_a, "opponent_abbreviation": abbr_a}
    return schedule


def fetch_week_schedule(week: int, season: int) -> dict[int, dict]:
    """Return {pro_team_id: {"abbreviation", "opponent_id", "opponent_abbreviation"}}
    for every NFL team playing this week. A team missing from the result is
    on a bye. Best-effort: returns {} on any network/parsing failure so a
    schedule outage never breaks a league sync.
    """
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(SCOREBOARD_URL, params={"week": week, "seasontype": 2, "year": season})
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return {}
    return _parse_scoreboard(data)


def fetch_season_schedule(season: int) -> dict[int, dict[int, dict]]:
    """Every regular-season week's matchups: {week: {pro_team_id: {...}}}.

    That's one scoreboard request per week, so the result is cached on disk
    for a day — otherwise every sync would re-fetch 18 weeks of a schedule
    that barely changes. Best-effort throughout: weeks that fail to fetch
    are simply absent, and a fully failed fetch returns {} rather than
    raising.
    """
    os.makedirs(SCHEDULE_CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(SCHEDULE_CACHE_DIR, f"season_{season}.json")

    if os.path.exists(cache_path) and (time.time() - os.path.getmtime(cache_path)) < SCHEDULE_CACHE_MAX_AGE_SECONDS:
        try:
            with open(cache_path) as f:
                cached = json.load(f)
            return {int(week): {int(tid): info for tid, info in teams.items()} for week, teams in cached.items()}
        except (OSError, ValueError):
            pass  # fall through and re-fetch

    season_schedule: dict[int, dict[int, dict]] = {}
    try:
        with httpx.Client(timeout=15.0) as client:
            for week in range(1, REGULAR_SEASON_WEEKS + 1):
                try:
                    resp = client.get(SCOREBOARD_URL, params={"week": week, "seasontype": 2, "year": season})
                    resp.raise_for_status()
                    parsed = _parse_scoreboard(resp.json())
                except (httpx.HTTPError, ValueError):
                    continue
                if parsed:
                    season_schedule[week] = parsed
    except httpx.HTTPError:
        return {}

    if not season_schedule:
        return {}

    tmp_path = cache_path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(season_schedule, f)
    os.replace(tmp_path, cache_path)
    return season_schedule


def compute_bye_weeks(season_schedule: dict[int, dict[int, dict]]) -> dict[int, int]:
    """{pro_team_id: bye week}. A team is on bye in the weeks it doesn't
    appear in — only weeks where the league as a whole is clearly playing
    (most teams present) count, so a week we failed to fetch isn't
    mistaken for 32 simultaneous byes."""
    playing_weeks: dict[int, set[int]] = {}
    valid_weeks = []
    for week, teams in season_schedule.items():
        if len(teams) < 20:  # a partially-fetched or off week — not trustworthy
            continue
        valid_weeks.append(week)
        for pro_team_id in teams:
            playing_weeks.setdefault(pro_team_id, set()).add(week)

    byes: dict[int, int] = {}
    for pro_team_id, weeks_played in playing_weeks.items():
        missing = sorted(set(valid_weeks) - weeks_played)
        if len(missing) == 1:
            byes[pro_team_id] = missing[0]
    return byes


class ESPNClientError(RuntimeError):
    pass


class ESPNClient:
    def __init__(self, league_id: int, season: int):
        self.league_id = league_id
        self.season = season
        self.base_url = BASE_URL.format(season=season, league_id=league_id)

    def _cookies(self) -> dict[str, str]:
        cookies = {}
        if settings.espn_s2:
            cookies["espn_s2"] = settings.espn_s2
        if settings.espn_swid:
            cookies["SWID"] = settings.espn_swid
        return cookies

    def _get(self, params: dict[str, Any], extra_headers: dict[str, str] | None = None) -> dict:
        headers = extra_headers or {}
        try:
            with httpx.Client(timeout=20.0) as client:
                resp = client.get(
                    self.base_url,
                    params=params,
                    cookies=self._cookies(),
                    headers=headers,
                )
        except httpx.HTTPError as exc:
            raise ESPNClientError(f"Could not reach ESPN: {exc}") from exc
        if resp.status_code == 401:
            raise ESPNClientError(
                "ESPN returned 401 Unauthorized. This league may be private; "
                "set ESPN_S2 and ESPN_SWID in backend/.env."
            )
        if resp.status_code == 404:
            raise ESPNClientError(
                f"League {self.league_id} not found for season {self.season}. "
                "Check the league ID and season."
            )
        try:
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ESPNClientError(f"ESPN returned an error: {exc}") from exc
        return resp.json()

    def get_league(self) -> dict:
        """League settings, scoring rules, teams, and rosters in one call."""
        return self._get({"view": ["mSettings", "mTeam", "mRoster", "mStatus"]})

    def get_boxscore(self, scoring_period_id: int) -> dict:
        """One past week's matchups including each team's lineup as it stood
        that week (slot assignments + what each player actually scored).

        This is the only way to know who was *started* in a past week —
        rosters synced from `get_league()` only ever reflect right now.
        """
        return self._get(
            {
                "view": ["mBoxscore", "mMatchupScore", "mRoster"],
                "scoringPeriodId": scoring_period_id,
            }
        )

    def get_free_agents(self, scoring_period_id: int, limit: int = 200) -> list[dict]:
        """Available (free agent + waiver) players with projected stats."""
        filter_payload = {
            "players": {
                "filterStatus": {"value": ["FREEAGENT", "WAIVERS"]},
                "limit": limit,
                "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
                "filterStatsForCurrentSeason": {"value": [self.season]},
            }
        }
        headers = {"x-fantasy-filter": json.dumps(filter_payload)}
        data = self._get(
            {"view": "kona_player_info", "scoringPeriodId": scoring_period_id},
            extra_headers=headers,
        )
        return data.get("players", [])
