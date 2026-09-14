"""Season-long "points left on the bench" tracker.

Every week you either started your best available lineup or you didn't,
and the gap is the cleanest measure of how much the start/sit call is
actually worth to you. Past lineups can't be reconstructed from the synced
roster (that only ever reflects right now), so each week is read from
ESPN's boxscore — which does remember who was in which slot — and scored
against the exact best lineup that roster could have produced
(app/lineup.py).

Weeks already computed are cached on the League, so only the current week
(still in progress) and any genuinely new week cost a request.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.espn_client import ESPNClient, ESPNClientError
from app.espn_constants import is_bench_slot, lineup_slot_label, position_from_id
from app.lineup import optimal_lineup
from app.models import League

IR_SLOT_ID = 21


def extract_team_lineup(boxscore: dict, espn_team_id: int, week: int) -> list[dict] | None:
    """This team's roster as it stood in `week`, with each player's slot and
    what they actually scored. None if the boxscore has nothing for them."""
    candidates = []
    for matchup in boxscore.get("schedule", []) or []:
        for side_key in ("home", "away"):
            side = matchup.get(side_key) or {}
            if side.get("teamId") != espn_team_id:
                continue
            roster = side.get("rosterForCurrentScoringPeriod") or {}
            entries = roster.get("entries") or []
            if entries:
                candidates.append((matchup.get("matchupPeriodId"), entries))

    if not candidates:
        return None
    # Leagues with multi-week matchup periods can return several; prefer the
    # one whose period matches the week we asked for.
    entries = next((e for period, e in candidates if period == week), candidates[0][1])

    lineup = []
    for entry in entries:
        pool = entry.get("playerPoolEntry") or {}
        player = pool.get("player") or {}
        slot_id = entry.get("lineupSlotId")
        if slot_id is None:
            continue
        lineup.append(
            {
                "espn_player_id": entry.get("playerId"),
                "name": player.get("fullName") or "Unknown",
                "position": position_from_id(player.get("defaultPositionId")),
                "slot_id": slot_id,
                "slot": lineup_slot_label(slot_id),
                "eligible_slots": player.get("eligibleSlots") or [],
                "points": pool.get("appliedStatTotal") or 0.0,
            }
        )
    return lineup or None


def score_week(lineup: list[dict]) -> dict:
    """Compare what was started against the best lineup that roster could
    have fielded that week."""
    started = [p for p in lineup if not is_bench_slot(p["slot_id"])]
    # Anyone not on IR was startable; bench players obviously, IR players not.
    available = [p for p in lineup if p["slot_id"] != IR_SLOT_ID]
    slot_ids = [p["slot_id"] for p in started]

    actual_points = sum(p["points"] for p in started)
    pairs, optimal_points = optimal_lineup(slot_ids, available)

    missed = []
    for (slot_id, best), actually_started in zip(pairs, started):
        if best is None or best["espn_player_id"] == actually_started["espn_player_id"]:
            continue
        missed.append(
            {
                "slot": lineup_slot_label(slot_id),
                "started": {"name": actually_started["name"], "points": round(actually_started["points"], 1)},
                "should_have_started": {"name": best["name"], "points": round(best["points"], 1)},
                "points_missed": round(best["points"] - actually_started["points"], 1),
            }
        )
    missed.sort(key=lambda m: m["points_missed"], reverse=True)

    return {
        "actual_points": round(actual_points, 1),
        "optimal_points": round(optimal_points, 1),
        "left_on_bench": round(optimal_points - actual_points, 1),
        "missed": missed,
    }


def get_bench_points(db: Session, league: League, my_team_id: int) -> dict:
    """Per-week and season totals, filling in any weeks not already cached
    on the League. Best-effort: a week ESPN won't serve is skipped rather
    than failing the whole report."""
    current_week = league.current_week or 1
    cache = dict(league.bench_points or {})
    team_cache = dict(cache.get(str(my_team_id), {}))

    client = ESPNClient(league_id=league.espn_league_id, season=league.season)
    fetched_any = False

    for week in range(1, current_week + 1):
        # The current week is still accruing points, so never trust a
        # cached copy of it.
        if str(week) in team_cache and week != current_week:
            continue
        try:
            boxscore = client.get_boxscore(scoring_period_id=week)
        except ESPNClientError:
            continue
        lineup = extract_team_lineup(boxscore, my_team_id, week)
        if not lineup:
            continue
        team_cache[str(week)] = {"week": week, **score_week(lineup)}
        fetched_any = True

    if fetched_any:
        cache[str(my_team_id)] = team_cache
        league.bench_points = cache
        db.commit()

    weeks = [team_cache[key] for key in sorted(team_cache, key=int)]
    # A week with no scores yet (not played) would otherwise dilute the
    # averages with a meaningless 0.
    played = [w for w in weeks if w["optimal_points"] > 0]

    total_left = sum(w["left_on_bench"] for w in played)
    worst = max(played, key=lambda w: w["left_on_bench"], default=None)

    return {
        "weeks": weeks,
        "weeks_counted": len(played),
        "total_left_on_bench": round(total_left, 1),
        "average_left_on_bench": round(total_left / len(played), 1) if played else 0.0,
        "total_actual": round(sum(w["actual_points"] for w in played), 1),
        "total_optimal": round(sum(w["optimal_points"] for w in played), 1),
        "worst_week": worst,
        "perfect_weeks": sum(1 for w in played if w["left_on_bench"] < 0.05),
    }
