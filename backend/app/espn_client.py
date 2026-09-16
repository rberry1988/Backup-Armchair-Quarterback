"""Thin wrapper around ESPN's undocumented fantasy football API.

Read-only throughout: nothing here ever submits a transaction, changes a
lineup, or writes anything back to ESPN.

Requests are made either anonymously (fine for a public league), with the
instance-wide ESPN_S2 / ESPN_SWID from .env, or as one specific user by
passing their own cookies to the constructor — see `_cookies`. That last
mode is what makes per-account private data such as pending waiver claims
readable at all, since ESPN scopes it to the session that owns it.
"""

from __future__ import annotations

import json
import os
import tempfile
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

    # A unique per-write temp name (not a fixed "<cache_path>.tmp") so two
    # concurrent syncs refreshing the same season's schedule cache can't
    # interleave writes to the same staging path before either renames it
    # into place.
    fd, tmp_path = tempfile.mkstemp(dir=SCHEDULE_CACHE_DIR, prefix=f"season_{season}.json.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(season_schedule, f)
        os.replace(tmp_path, cache_path)
    except BaseException:
        os.unlink(tmp_path)
        raise
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


def normalize_swid(swid: str | None) -> str:
    """ESPN's SWID cookie is a brace-wrapped UUID ("{XXXXXXXX-....}"), and
    it rejects the value without the braces. People copying it out of their
    browser's cookie inspector routinely lose them, so put them back rather
    than failing with an opaque 401."""
    if not swid:
        return ""
    swid = swid.strip()
    if not swid:
        return ""
    if not swid.startswith("{"):
        swid = "{" + swid
    if not swid.endswith("}"):
        swid = swid + "}"
    return swid


class ESPNClientError(RuntimeError):
    pass


class ESPNClient:
    def __init__(
        self,
        league_id: int,
        season: int,
        espn_s2: str | None = None,
        espn_swid: str | None = None,
    ):
        """`espn_s2`/`espn_swid` are one specific person's ESPN session (see
        User.espn_s2 in models.py). When given they're used *instead of* the
        operator-level cookies in backend/.env, never merged with them —
        mixing a caller's SWID with the operator's espn_s2 would just be a
        broken session, and silently falling back to the operator's would
        return that person's private data under someone else's request."""
        self.league_id = league_id
        self.season = season
        self.base_url = BASE_URL.format(season=season, league_id=league_id)
        self.espn_s2 = espn_s2
        self.espn_swid = espn_swid

    @property
    def is_authenticated_as_user(self) -> bool:
        """True when this client is acting as a specific person's ESPN
        account rather than the instance's shared credentials."""
        return bool(self.espn_s2 and self.espn_swid)

    def _cookies(self) -> dict[str, str]:
        if self.is_authenticated_as_user:
            return {"espn_s2": self.espn_s2, "SWID": normalize_swid(self.espn_swid)}
        cookies = {}
        if settings.espn_s2:
            cookies["espn_s2"] = settings.espn_s2
        if settings.espn_swid:
            cookies["SWID"] = normalize_swid(settings.espn_swid)
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
                "ESPN returned 401 Unauthorized. This league is private, or the ESPN session "
                "being used has expired. Connect your ESPN account under Settings \u2192 Account "
                "(or set ESPN_S2 and ESPN_SWID in backend/.env for the whole instance)."
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
        try:
            return resp.json()
        except ValueError as exc:
            # A 200 carrying something that isn't JSON: a Cloudflare
            # interstitial, an ESPN maintenance page, a truncated body.
            # Without this the JSONDecodeError escapes as a bare ValueError,
            # straight past every `except ESPNClientError` in the codebase —
            # so a sync, a pending-claims fetch or a bench-points lookup
            # would 500 instead of reporting that ESPN is misbehaving. Every
            # other client here already guards this; this one is the most
            # used and was the only one that didn't.
            raise ESPNClientError(
                "ESPN returned a response that wasn't JSON. It's usually a temporary block or "
                "maintenance page — try again in a few minutes."
            ) from exc

    def get_league(self) -> dict:
        """League settings, scoring rules, teams, rosters and the season's
        head-to-head schedule in one call. mMatchup rides along for free —
        it's who plays whom each week, with no per-player detail, which is
        all the matchup preview needs."""
        return self._get({"view": ["mSettings", "mTeam", "mRoster", "mStatus", "mMatchup"]})

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

    def get_pending_transactions(self) -> dict:
        """Everything this ESPN account has submitted but that hasn't been
        processed yet — waiver claims, free-agent adds queued for the next
        processing run, and proposed trades.

        ESPN scopes this view to whoever the request's cookies belong to, so
        it is empty (not an error) when called without an authenticated
        session. mTeam rides along to name the teams involved.
        """
        return self._get({"view": ["mPendingTransactions", "mTeam", "mStatus"]})

    def get_players_by_id(self, player_ids: list[int]) -> list[dict]:
        """Look up specific players by ESPN id. Pending transactions carry
        only ids, and a claim for someone outside the synced player pool
        (deep waiver-wire adds, mainly) would otherwise show as a bare
        number."""
        if not player_ids:
            return []
        filter_payload = {"players": {"filterIds": {"value": player_ids}, "limit": len(player_ids)}}
        data = self._get(
            {"view": "kona_player_info"},
            extra_headers={"x-fantasy-filter": json.dumps(filter_payload)},
        )
        return data.get("players", [])

    def get_transactions(self) -> dict:
        """The league's completed transaction log — every add, drop, waiver
        claim and trade, with the FAAB paid where there was one.

        Public for a public league; a private one needs the requesting
        user's own cookies, same as everything else here.
        """
        return self._get({"view": ["mTransactions2", "mTeam"]})
