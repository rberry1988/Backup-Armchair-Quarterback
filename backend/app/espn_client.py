"""Thin wrapper around ESPN's undocumented public fantasy football API.

Only the read-only endpoints needed for a public league are used:
no login/cookie flow is implemented. If ESPN ever requires cookies for a
league that used to be public, set ESPN_S2 / ESPN_SWID in .env and they'll
be sent automatically (see `_cookies`).
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import settings

BASE_URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}/segments/0/leagues/{league_id}"


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
        with httpx.Client(timeout=20.0) as client:
            resp = client.get(
                self.base_url,
                params=params,
                cookies=self._cookies(),
                headers=headers,
            )
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
        resp.raise_for_status()
        return resp.json()

    def get_league(self) -> dict:
        """League settings, scoring rules, teams, and rosters in one call."""
        return self._get({"view": ["mSettings", "mTeam", "mRoster", "mStatus"]})

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
