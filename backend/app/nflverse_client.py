"""Fetches advanced stats ESPN's API doesn't expose (target share, air
yards share, WOPR, snap %) from nflverse — the free, open-source play-by-play
data project the fantasy analytics community runs on. Data is published as
plain CSV files on GitHub releases, no auth needed.

Everything here is best-effort: any network/parsing failure returns an
empty result rather than raising, so a slow or unreachable nflverse never
breaks an ESPN sync — it just means advanced stats/matchup ratings are
unavailable until the next successful sync.
"""

from __future__ import annotations

import csv
import os
import tempfile
import time

import httpx

CROSSWALK_URL = "https://raw.githubusercontent.com/dynastyprocess/data/master/files/db_playerids.csv"
PLAYER_STATS_URL = "https://github.com/nflverse/nflverse-data/releases/download/player_stats/player_stats.csv"
SNAP_COUNTS_URL_TEMPLATE = (
    "https://github.com/nflverse/nflverse-data/releases/download/snap_counts/snap_counts_{season}.csv"
)

CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "nflverse_cache")
CACHE_MAX_AGE_SECONDS = 6 * 60 * 60  # 6 hours — nflverse only updates after games are played


def _cached_download(url: str, cache_filename: str) -> str | None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(CACHE_DIR, cache_filename)

    if os.path.exists(cache_path) and (time.time() - os.path.getmtime(cache_path)) < CACHE_MAX_AGE_SECONDS:
        return cache_path

    try:
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            resp = client.get(url)
        resp.raise_for_status()
    except httpx.HTTPError:
        return cache_path if os.path.exists(cache_path) else None

    # A unique per-write temp name (not a fixed "<cache_path>.tmp") so two
    # concurrent syncs refreshing the same cache file can't interleave
    # writes to the same staging path before either renames it into place.
    fd, tmp_path = tempfile.mkstemp(dir=CACHE_DIR, prefix=cache_filename + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(resp.content)
        os.replace(tmp_path, cache_path)
    except BaseException:
        os.unlink(tmp_path)
        raise
    return cache_path


def fetch_id_crosswalk() -> dict[int, dict[str, str]]:
    """Return {espn_id: {"gsis_id": ..., "pfr_id": ..., "fantasypros_id": ...}}.

    This dynastyprocess file isn't nflverse-specific — it's a general
    player-id crosswalk — but it lives here since nflverse was the first
    consumer. app/fantasypros_client.py also uses the fantasypros_id
    column to join FantasyPros' rankings onto our ESPN-keyed players.
    """
    path = _cached_download(CROSSWALK_URL, "db_playerids.csv")
    if path is None:
        return {}
    result: dict[int, dict[str, str]] = {}
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                espn_id = row.get("espn_id")
                if not espn_id or espn_id == "NA":
                    continue
                try:
                    espn_id_int = int(float(espn_id))
                except ValueError:
                    continue
                result[espn_id_int] = {
                    "gsis_id": row.get("gsis_id") or "",
                    "pfr_id": row.get("pfr_id") or "",
                    "fantasypros_id": row.get("fantasypros_id") or "",
                }
    except (OSError, csv.Error):
        return {}
    return result


_NUMERIC_STAT_FIELDS = [
    "carries",
    "targets",
    "receptions",
    "receiving_yards",
    "receiving_air_yards",
    "receiving_yards_after_catch",
    "target_share",
    "air_yards_share",
    "wopr",
    "racr",
    "fantasy_points",
    "fantasy_points_ppr",
]


def fetch_weekly_player_stats(season: int) -> list[dict]:
    """Return every row for `season` from nflverse's combined weekly player
    stats file (all seasons since 1999 in one ~33MB CSV; we filter while
    streaming so memory stays bounded to one season's rows).
    """
    path = _cached_download(PLAYER_STATS_URL, "player_stats.csv")
    if path is None:
        return []
    season_str = str(season)
    rows: list[dict] = []
    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("season") != season_str:
                    continue
                parsed = {
                    "player_id": row.get("player_id"),
                    "position": row.get("position"),
                    "week": row.get("week"),
                    "opponent_team": row.get("opponent_team"),
                    "recent_team": row.get("recent_team"),
                }
                for field in _NUMERIC_STAT_FIELDS:
                    raw = row.get(field)
                    parsed[field] = float(raw) if raw not in (None, "") else None
                rows.append(parsed)
    except (OSError, csv.Error):
        return []
    return rows


def fetch_snap_counts(season: int) -> list[dict]:
    """Return this season's snap-count rows, keyed by pfr_player_id."""
    url = SNAP_COUNTS_URL_TEMPLATE.format(season=season)
    path = _cached_download(url, f"snap_counts_{season}.csv")
    if path is None:
        return []
    rows: list[dict] = []
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                offense_pct = row.get("offense_pct")
                rows.append(
                    {
                        "pfr_player_id": row.get("pfr_player_id"),
                        "week": row.get("week"),
                        "offense_pct": float(offense_pct) if offense_pct not in (None, "") else None,
                    }
                )
    except (OSError, csv.Error):
        return []
    return rows
