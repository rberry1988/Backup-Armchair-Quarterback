from __future__ import annotations

from sqlalchemy.orm import Session

from app.consistency import get_consistency
from app.matchup import get_matchup_context
from app.models import League, Player, Team
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


def _budget_context(db: Session, league: League | None, my_team_id: int) -> dict | None:
    """What everyone in the league can actually still spend.

    Turns the bid suggestion from a percentage of an imagined budget into
    real money against a real remaining balance — and, just as usefully,
    says who can outbid you. Returns None when the league was synced before
    these fields were captured, so callers can fall back to the percentage
    rather than render zeros as fact.
    """
    if league is None:
        return None

    teams = db.query(Team).filter(Team.league_id == league.id).all()
    if not teams:
        return None

    mine = next((t for t in teams if t.espn_team_id == my_team_id), None)

    if league.uses_faab and league.acquisition_budget > 0:
        budget = league.acquisition_budget

        def remaining(team: Team) -> int:
            # Clamped: a mid-season budget change can leave spend above the
            # current budget, and "-$4 left" is worse than saying nothing.
            return max(0, int(round(budget - (team.faab_spent or 0.0))))

        rivals = sorted(
            ({"team": t.name, "remaining": remaining(t)} for t in teams if t.espn_team_id != my_team_id),
            key=lambda r: r["remaining"],
            reverse=True,
        )
        return {
            "type": "faab",
            "budget": budget,
            "my_remaining": remaining(mine) if mine else None,
            "rivals": rivals,
            # The number that decides whether a bid is safe: you only have
            # to beat the richest rival, not the whole table.
            "top_rival_remaining": rivals[0]["remaining"] if rivals else None,
        }

    ranks = [t for t in teams if t.waiver_rank is not None]
    if ranks:
        order = sorted(ranks, key=lambda t: t.waiver_rank)
        return {
            "type": "priority",
            "my_rank": mine.waiver_rank if mine else None,
            "teams_ranked": len(order),
            "order": [{"team": t.name, "rank": t.waiver_rank} for t in order],
        }

    return None


def _suggested_bid(point_upgrade: float, budget: dict | None) -> int | None:
    """The percentage suggestion converted to this league's real money, and
    never more than is actually left to spend. None when there's no budget
    to convert against."""
    if not budget or budget.get("type") != "faab":
        return None
    pct = _suggested_faab_pct(point_upgrade)
    bid = round(budget["budget"] * pct / 100)
    remaining = budget.get("my_remaining")
    if remaining is not None:
        bid = min(bid, remaining)
    # Every row that reaches here already cleared the bar for being an
    # upgrade, so suggesting $0 for one contradicts the suggestion itself —
    # and a $0 claim loses every tie in most leagues. Floor it at a dollar,
    # unless there's genuinely nothing left to spend.
    if point_upgrade > 0 and (remaining is None or remaining > 0):
        bid = max(1, bid)
    return bid


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


def get_waiver_targets(
    db: Session, league_id: int, my_team_id: int, top_n: int = 5, include_budget: bool = False
) -> dict:
    """Two different questions, answered separately.

    "This week" ranks by the trend/matchup-adjusted projection — who helps
    you win on Sunday. "Rest of season" ranks by FantasyCalc's market trade
    value, which is a consensus read on a player's worth for the remainder
    of the season rather than one week of it. They deliberately disagree:
    the best streamer this week is often not the best asset to hold, and a
    valuable stash frequently has a poor or missing projection right now.
    """
    team = get_my_team(db, league_id, my_team_id)
    if team is None:
        return {"error": "team_not_found"}

    league = db.get(League, league_id)
    fc_values = (league.fantasycalc_values or {}) if league else {}
    # Premium: real budgets and waiver order. Basic accounts keep the
    # percentage heuristic, which needs nothing from ESPN.
    budget = _budget_context(db, league, my_team_id) if include_budget else None

    def fc_value(player: Player) -> int:
        entry = fc_values.get(str(player.espn_player_id)) or {}
        return entry.get("value") or 0

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

    # Pass 1: a rough pre-filter per position, wide enough (top_n * 3) that
    # a player trending up but not yet leading on raw points still has a
    # shot at the final cut once trend/matchup are factored in below --
    # while still bounding the batched trend/consistency lookups to a
    # reasonable pool instead of the whole free-agent list.
    #
    # The two lenses need separate pools: pre-filtering the rest-of-season
    # list by projected points would throw away exactly the players it
    # exists to surface -- high-value assets whose current-week projection
    # is low or missing.
    week_pools: dict[str, tuple[list[Player], Player | None]] = {}
    ros_pools: dict[str, tuple[list[Player], Player | None]] = {}
    for position in POSITIONS:
        mine = my_players_by_position.get(position, [])
        weakest_by_points = min(mine, key=points_or_default) if mine else None
        weakest_by_value = min(mine, key=fc_value) if mine else None

        at_position = [p for p in free_agents if p.position == position]

        # Injured-out players can't help this week, but for rest-of-season
        # they're often the whole point of the pickup, so they stay in.
        week_candidates = sorted(
            (p for p in at_position if p.injury_status not in INJURED_OUT_STATUSES),
            key=points_or_default,
            reverse=True,
        )[: top_n * 3]
        if week_candidates:
            week_pools[position] = (week_candidates, weakest_by_points)

        ros_candidates = [p for p in sorted(at_position, key=fc_value, reverse=True) if fc_value(p) > 0][: top_n * 3]
        if ros_candidates:
            ros_pools[position] = (ros_candidates, weakest_by_value)

    # One batched query each across both pools (plus the rostered players
    # the baselines compare against) instead of one per candidate.
    lookup_players: list[Player] = []
    for pools in (week_pools, ros_pools):
        for pool, weakest in pools.values():
            lookup_players.extend(pool)
            if weakest is not None:
                lookup_players.append(weakest)
    seen: set[int] = set()
    deduped = [p for p in lookup_players if not (p.espn_player_id in seen or seen.add(p.espn_player_id))]

    trends = get_player_trends(db, league_id, [(p.espn_player_id, p.position) for p in deduped])
    consistency = get_consistency(db, league_id, [p.espn_player_id for p in deduped])

    def matchup_for(player: Player) -> dict | None:
        return get_matchup_context(league, player.pro_team_id, player.position) if league else None

    def value_for(player: Player) -> float:
        return _adjusted_value(
            player,
            trends.get(player.espn_player_id),
            matchup_for(player),
            consistency.get(player.espn_player_id),
        )

    def add_payload(candidate: Player) -> dict:
        return {
            # Needed by the planned-moves feature to record which player a
            # planned claim is for; Player row ids don't survive a sync.
            "espn_player_id": candidate.espn_player_id,
            "name": candidate.full_name,
            "projected_points": candidate.projected_points,
            "percent_owned": round(candidate.percent_owned, 1),
            "injury_status": candidate.injury_status,
            "matchup": matchup_for(candidate),
            "trend": trends.get(candidate.espn_player_id),
            "fantasycalc": fc_values.get(str(candidate.espn_player_id)),
        }

    this_week = []
    for position, (pool, weakest) in week_pools.items():
        baseline = value_for(weakest) if weakest else 0.0
        suggestions = []
        for candidate in sorted(pool, key=value_for, reverse=True):
            candidate_value = value_for(candidate)
            if weakest is not None and candidate_value <= baseline:
                continue
            point_upgrade = round(candidate_value - baseline, 1)
            suggestions.append(
                {
                    "add": add_payload(candidate),
                    "drop_candidate": (
                        {"espn_player_id": weakest.espn_player_id, "name": weakest.full_name,
                         "projected_points": weakest.projected_points}
                        if weakest
                        else None
                    ),
                    "point_upgrade": point_upgrade,
                    "suggested_faab_pct": _suggested_faab_pct(point_upgrade),
                    "suggested_bid": _suggested_bid(point_upgrade, budget),
                }
            )
            if len(suggestions) >= top_n:
                break
        if suggestions:
            this_week.append({"position": position, "suggestions": suggestions})

    rest_of_season = []
    for position, (pool, weakest) in ros_pools.items():
        baseline = fc_value(weakest) if weakest else 0
        suggestions = []
        for candidate in pool:
            if weakest is not None and fc_value(candidate) <= baseline:
                continue
            suggestions.append(
                {
                    "add": add_payload(candidate),
                    "drop_candidate": (
                        {"espn_player_id": weakest.espn_player_id, "name": weakest.full_name,
                         "fantasycalc_value": baseline}
                        if weakest
                        else None
                    ),
                    # No FAAB suggestion here on purpose: the existing one is
                    # calibrated against a projected-points upgrade, and
                    # inventing a second mapping from market value to bid %
                    # would be a made-up number dressed up as advice.
                    "value_upgrade": fc_value(candidate) - baseline,
                }
            )
            if len(suggestions) >= top_n:
                break
        if suggestions:
            rest_of_season.append({"position": position, "suggestions": suggestions})

    return {
        "team": team.name,
        "this_week": this_week,
        "rest_of_season": rest_of_season,
        # Lets the UI explain an empty rest-of-season list ("re-sync to pull
        # market values") instead of just showing nothing.
        "fantasycalc_available": bool(fc_values),
        # None for basic accounts, and for premium accounts whose league was
        # synced before these fields were captured — the UI keeps showing the
        # percentage heuristic in both cases rather than inventing a budget.
        "budget": budget,
    }
