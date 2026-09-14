"""Inferred NFL depth charts and RB handcuff finder.

ESPN doesn't expose an official depth-chart API (only an HTML page), so
this ranks players within each (pro_team, position) group using the same
usage signals the rest of the app already collects: nflverse's real
snap % when available, falling back to ESPN's percent_started and then
projected_points for players nflverse has no crosswalk match for (deep
bench players, rookies not yet in a weekly release, etc). This is a
proxy for a team's actual depth chart, not the official one.

The player pool is whatever's in the `players` table for this league:
every rostered player plus the free agents synced each week (see
sync_service.py, currently top-200 by ownership). Very deep, widely
unowned bench players may be missing — acceptable since they wouldn't be
meaningful handcuffs anyway.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy.orm import Session

from app.espn_constants import pro_team_abbr
from app.models import Player, PlayerWeekStat, RosterEntry, Team

DEPTH_CHART_POSITIONS = {"QB", "RB", "WR", "TE", "K"}


def _latest_snap_pct_by_player(db: Session, league_id: int, espn_ids: list[int]) -> dict[int, float]:
    """One query for every player's most recent known snap %, instead of
    one query each. Rows are ordered newest-week-first per player, so the
    first row with a snap_pct value is the latest available one — a bye
    week or a week with no nflverse match yet is skipped rather than
    treated as "no snaps"."""
    if not espn_ids:
        return {}

    rows = (
        db.query(PlayerWeekStat.espn_player_id, PlayerWeekStat.advanced_stats)
        .filter(PlayerWeekStat.league_id == league_id, PlayerWeekStat.espn_player_id.in_(espn_ids))
        .order_by(PlayerWeekStat.espn_player_id, PlayerWeekStat.week.desc())
        .all()
    )

    result: dict[int, float] = {}
    for espn_id, advanced_stats in rows:
        if espn_id in result:
            continue
        snap_pct = (advanced_stats or {}).get("snap_pct")
        if snap_pct is not None:
            result[espn_id] = snap_pct
    return result


def _owner_by_player_id(db: Session, league_id: int) -> dict[int, tuple[int, str]]:
    rows = (
        db.query(RosterEntry.player_id, Team.id, Team.name)
        .join(Team, RosterEntry.team_id == Team.id)
        .filter(Team.league_id == league_id)
        .all()
    )
    return {player_id: (team_id, team_name) for player_id, team_id, team_name in rows}


def _depth_score(player: Player, snap_pct_by_id: dict[int, float]) -> tuple[int, float, float]:
    """Sorts descending: real snap % always outranks the fallback tier, so
    a well-documented backup never gets bumped by an untracked player who
    merely has a higher percent_started."""
    snap_pct = snap_pct_by_id.get(player.espn_player_id)
    if snap_pct is not None:
        return (2, snap_pct, player.projected_points or 0.0)
    return (1, player.percent_started, player.projected_points or 0.0)


def compute_depth_charts(db: Session, league_id: int) -> dict[str, dict[str, list[dict]]]:
    """Returns {pro_team_abbr: {position: [player dicts by depth_rank]}}
    for every NFL team with at least one synced player."""
    players = (
        db.query(Player)
        .filter(
            Player.league_id == league_id,
            Player.position.in_(DEPTH_CHART_POSITIONS),
            Player.pro_team_id > 0,
        )
        .all()
    )
    if not players:
        return {}

    snap_pct_by_id = _latest_snap_pct_by_player(db, league_id, [p.espn_player_id for p in players])
    owner_by_player_id = _owner_by_player_id(db, league_id)

    grouped: dict[str, dict[str, list[Player]]] = defaultdict(lambda: defaultdict(list))
    for player in players:
        grouped[pro_team_abbr(player.pro_team_id)][player.position].append(player)

    charts: dict[str, dict[str, list[dict]]] = {}
    for team_abbr, by_position in grouped.items():
        charts[team_abbr] = {}
        for position, position_players in by_position.items():
            ranked_players = sorted(
                position_players, key=lambda p: _depth_score(p, snap_pct_by_id), reverse=True
            )
            entries = []
            for depth_rank, player in enumerate(ranked_players, start=1):
                owner = owner_by_player_id.get(player.id)
                entries.append(
                    {
                        "espn_player_id": player.espn_player_id,
                        "name": player.full_name,
                        "position": player.position,
                        "pro_team": team_abbr,
                        "depth_rank": depth_rank,
                        "snap_pct": snap_pct_by_id.get(player.espn_player_id),
                        "percent_started": player.percent_started,
                        "projected_points": player.projected_points,
                        "injury_status": player.injury_status,
                        "is_free_agent": player.is_free_agent,
                        "owner_team_id": owner[0] if owner else None,
                        "owner_team_name": owner[1] if owner else None,
                    }
                )
            charts[team_abbr][position] = entries
    return charts


def get_rb_handcuffs(db: Session, league_id: int, my_team_id: int) -> list[dict]:
    """For each RB on my roster, find the next-ranked RB on the same NFL
    team per the inferred depth chart (their "handcuff") and report that
    handcuff's roster status. Skips RBs who are their team's clear
    lead-back with no depth-chart backup on file, and RBs already at the
    bottom of their own team's chart (nothing to hand-cuff to)."""
    depth_charts = compute_depth_charts(db, league_id)

    my_rbs = (
        db.query(Player)
        .join(RosterEntry, RosterEntry.player_id == Player.id)
        .join(Team, RosterEntry.team_id == Team.id)
        .filter(Team.league_id == league_id, Team.espn_team_id == my_team_id, Player.position == "RB")
        .all()
    )

    handcuffs = []
    for rb in my_rbs:
        team_abbr = pro_team_abbr(rb.pro_team_id)
        rb_chart = depth_charts.get(team_abbr, {}).get("RB", [])
        my_entry = next((e for e in rb_chart if e["espn_player_id"] == rb.espn_player_id), None)
        if my_entry is None:
            continue

        handcuff_entry = next((e for e in rb_chart if e["depth_rank"] == my_entry["depth_rank"] + 1), None)
        if handcuff_entry is None:
            continue

        if handcuff_entry["is_free_agent"]:
            status = "free_agent"
        elif handcuff_entry["owner_team_id"] is not None and handcuff_entry["owner_team_id"] == my_entry.get(
            "owner_team_id"
        ):
            status = "mine"
        else:
            status = "rostered"

        handcuffs.append(
            {
                "rb": {
                    "espn_player_id": rb.espn_player_id,
                    "name": rb.full_name,
                    "pro_team": team_abbr,
                    "depth_rank": my_entry["depth_rank"],
                },
                "handcuff": handcuff_entry,
                "status": status,
            }
        )

    return handcuffs
