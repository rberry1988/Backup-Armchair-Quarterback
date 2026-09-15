from __future__ import annotations

from sqlalchemy.orm import Session

from app.consistency import get_consistency
from app.matchup import get_matchup_context
from app.models import League, Player
from app.recommendations.common import (
    INJURED_OUT_STATUSES,
    get_my_team,
    points_or_default,
    roster_with_players,
)
from app.trends import get_player_trends

POSITIONS = ["QB", "RB", "WR", "TE", "K", "D/ST"]

# How much a rising/falling usage trend or a favorable/tough matchup should
# move a player's raw projection when ranking waiver targets. Usage
# (targets, carries, snap share) moves before fantasy points do, so a
# player trending up with a soft upcoming matchup can be a better add than
# their current single-week projection alone suggests -- and vice versa.
TREND_UP_MULTIPLIER = 1.15
TREND_DOWN_MULTIPLIER = 0.90
MATCHUP_FAVORABLE_MULTIPLIER = 1.05
MATCHUP_TOUGH_MULTIPLIER = 0.95

# Suggested FAAB bid as a % of a standard 100-point budget, scaled by how
# much the pickup's trend/matchup-adjusted value projects to add over what
# it replaces. Purely a starting-point heuristic — irrelevant if your
# league uses waiver priority instead of FAAB.
def _suggested_faab_pct(point_upgrade: float) -> int:
    return max(0, min(35, round(point_upgrade * 2.5)))


def _headline_trend_direction(trend: dict | None) -> str | None:
    if not trend:
        return None
    # `stats` is built in POSITION_TREND_STATS' priority order (see
    # trends.py), so the first entry is the headline usage stat for the
    # position -- e.g. targets for a WR, carries for a RB.
    headline = next(iter(trend["stats"].values()), None)
    return headline["trend"] if headline else None


def _adjusted_value(player: Player, trend: dict | None, matchup_ctx: dict | None, consistency: dict | None) -> float:
    """A player's raw projection, nudged by early signals a single-week
    ESPN projection doesn't capture. Falls back to recent actual-point
    average when there's no usable projection at all -- common for deep
    free agents ESPN hasn't bothered projecting, whose own recent
    production is a far better signal than a missing/zero placeholder."""
    base = points_or_default(player)
    if base == 0.0 and consistency:
        base = consistency["average"]

    direction = _headline_trend_direction(trend)
    if direction == "up":
        base *= TREND_UP_MULTIPLIER
    elif direction == "down":
        base *= TREND_DOWN_MULTIPLIER

    matchup_label = matchup_ctx["label"] if matchup_ctx else None
    if matchup_label == "favorable matchup":
        base *= MATCHUP_FAVORABLE_MULTIPLIER
    elif matchup_label == "tough matchup":
        base *= MATCHUP_TOUGH_MULTIPLIER

    return base


def get_waiver_targets(db: Session, league_id: int, my_team_id: int, top_n: int = 5) -> dict:
    team = get_my_team(db, league_id, my_team_id)
    if team is None:
        return {"error": "team_not_found"}

    league = db.get(League, league_id)

    my_entries = roster_with_players(db, team.id)
    my_players_by_position: dict[str, list[Player]] = {pos: [] for pos in POSITIONS}
    for entry in my_entries:
        my_players_by_position.setdefault(entry.player.position, []).append(entry.player)

    my_rostered_espn_ids = {e.player.espn_player_id for e in my_entries}

    free_agents = (
        db.query(Player)
        .filter(Player.league_id == league_id, Player.is_free_agent.is_(True))
        .all()
    )
    free_agents = [p for p in free_agents if p.espn_player_id not in my_rostered_espn_ids]

    # Pass 1: a rough, points-only pre-filter per position, wide enough
    # (top_n * 3) that a player trending up but not yet leading on raw
    # points still has a shot at making the final cut once trend/matchup
    # are factored in below -- while still bounding the batched
    # trend/consistency lookups to a reasonable pool instead of the whole
    # free-agent list.
    pool_by_position: dict[str, tuple[list[Player], Player | None]] = {}
    for position in POSITIONS:
        my_players = sorted(
            my_players_by_position.get(position, []),
            key=lambda p: points_or_default(p),
            reverse=True,
        )
        weakest_rostered = my_players[-1] if my_players else None

        candidates = [p for p in free_agents if p.position == position and p.injury_status not in INJURED_OUT_STATUSES]
        candidates.sort(key=lambda p: points_or_default(p), reverse=True)
        pool = candidates[: top_n * 3]
        if pool:
            pool_by_position[position] = (pool, weakest_rostered)

    # One batched query each for every player across every position's pool
    # (plus each position's weakest rostered player, needed to compute an
    # apples-to-apples adjusted baseline) instead of one per candidate.
    lookup_players: list[Player] = []
    for pool, weakest_rostered in pool_by_position.values():
        lookup_players.extend(pool)
        if weakest_rostered is not None:
            lookup_players.append(weakest_rostered)
    lookup_ids = [(p.espn_player_id, p.position) for p in lookup_players]
    lookup_espn_ids = [p.espn_player_id for p in lookup_players]

    trends = get_player_trends(db, league_id, lookup_ids)
    consistency = get_consistency(db, league_id, lookup_espn_ids)

    def matchup_for(player: Player) -> dict | None:
        return get_matchup_context(league, player.pro_team_id, player.position) if league else None

    def value_for(player: Player) -> float:
        return _adjusted_value(
            player,
            trends.get(player.espn_player_id),
            matchup_for(player),
            consistency.get(player.espn_player_id),
        )

    results = []
    for position, (pool, weakest_rostered) in pool_by_position.items():
        baseline = value_for(weakest_rostered) if weakest_rostered else 0.0

        ranked = sorted(pool, key=value_for, reverse=True)
        suggestions = []
        for candidate in ranked:
            candidate_value = value_for(candidate)
            if weakest_rostered is not None and candidate_value <= baseline:
                continue
            point_upgrade = round(candidate_value - baseline, 1)
            suggestions.append(
                {
                    "add": {
                        "name": candidate.full_name,
                        "projected_points": candidate.projected_points,
                        "percent_owned": round(candidate.percent_owned, 1),
                        "injury_status": candidate.injury_status,
                        "matchup": matchup_for(candidate),
                        "trend": trends.get(candidate.espn_player_id),
                    },
                    "drop_candidate": (
                        {"name": weakest_rostered.full_name, "projected_points": weakest_rostered.projected_points}
                        if weakest_rostered
                        else None
                    ),
                    "point_upgrade": point_upgrade,
                    "suggested_faab_pct": _suggested_faab_pct(point_upgrade),
                }
            )
            if len(suggestions) >= top_n:
                break
        if suggestions:
            results.append({"position": position, "suggestions": suggestions})

    return {"team": team.name, "recommendations": results}
