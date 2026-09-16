"""Reading the parts of ESPN's league/team payloads this app was fetching
but throwing away: how free agents are acquired, and where each team
stands on budget and waiver order.

Every sync already asks for the mSettings and mTeam views — these fields
ride along in bytes we were paying for anyway. Parsed defensively, as with
everything else from ESPN's undocumented API: a missing or renamed field
yields a falsy default rather than an exception, so a payload change
degrades the waiver advice instead of breaking a sync.
"""

from __future__ import annotations

from typing import Any


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def acquisition_settings(league_json: dict) -> dict:
    """{"uses_faab": bool, "budget": int} for the league.

    ESPN exposes a FAAB budget under settings.acquisitionSettings. A league
    on waiver priority instead reports no budget (or zero), which is what
    `uses_faab` False means — not that the data was missing.
    """
    settings = (league_json.get("settings") or {}).get("acquisitionSettings") or {}
    budget = _as_number(settings.get("acquisitionBudget"))
    # ESPN has shipped this flag under two names across seasons; either
    # confirms FAAB, and a positive budget confirms it on its own.
    flagged = bool(settings.get("isUsingAcquisitionBudget") or settings.get("usingAcquisitionBudget"))
    uses_faab = flagged or bool(budget and budget > 0)
    return {
        "uses_faab": uses_faab,
        "budget": int(budget) if uses_faab and budget and budget > 0 else 0,
    }


def team_acquisition_state(team_json: dict) -> dict:
    """{"faab_spent": float, "waiver_rank": int | None, "acquisitions": int}
    for one team.

    waiver_rank is only meaningful in a priority league and faab_spent only
    in a FAAB one, so both are reported as found rather than inferred from
    each other — the caller knows which the league uses.
    """
    counter = team_json.get("transactionCounter") or {}
    spent = _as_number(counter.get("acquisitionBudgetSpent"))
    acquisitions = _as_number(counter.get("acquisitions"))
    rank = _as_number(team_json.get("waiverRank"))
    return {
        "faab_spent": spent if spent is not None else 0.0,
        # Rank 0 isn't a real waiver position; ESPN uses it for "unset".
        "waiver_rank": int(rank) if rank and rank > 0 else None,
        "acquisitions": int(acquisitions) if acquisitions is not None else 0,
    }


def fantasy_schedule(league_json: dict) -> dict[str, list[list[int]]]:
    """Who plays whom, by week: {"3": [[home_team_id, away_team_id], ...]}.

    ESPN calls these matchup periods rather than weeks; in the vast
    majority of leagues they're the same thing, and a league using
    multi-week periods simply gets both weeks pointing at the same pairing,
    which is correct.

    Byes exist in odd-sized leagues, where a matchup has only one side.
    Those are skipped rather than half-recorded.
    """
    schedule: dict[str, list[list[int]]] = {}
    for matchup in league_json.get("schedule") or []:
        if not isinstance(matchup, dict):
            continue
        period = matchup.get("matchupPeriodId")
        home = (matchup.get("home") or {}).get("teamId")
        away = (matchup.get("away") or {}).get("teamId")
        if period is None or not isinstance(home, int) or not isinstance(away, int):
            continue
        try:
            week = int(period)
        except (TypeError, ValueError):
            continue
        schedule.setdefault(str(week), []).append([home, away])
    return schedule


def opponent_for(schedule: dict, team_id: int, week: int) -> int | None:
    """The team `team_id` faces in `week`, or None on a bye / unknown week."""
    for home, away in (schedule or {}).get(str(week), []):
        if home == team_id:
            return away
        if away == team_id:
            return home
    return None
