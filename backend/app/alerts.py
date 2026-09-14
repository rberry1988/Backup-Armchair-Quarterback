"""Roster alerts: the players on your team who need a decision this week,
each paired with the replacements you could actually make.

The pieces already existed separately — injury status on the roster, the
inferred depth chart, the free-agent pool — but finding "my RB is
Doubtful, who's his backup, and can I still get him?" meant three tabs and
a mental join. This does that join.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.depth_charts import compute_depth_charts
from app.espn_constants import pro_team_abbr
from app.models import League, Player, RosterEntry, Team

# Worth surfacing a replacement for. QUESTIONABLE is included deliberately:
# it's the status where having the backup already identified matters most,
# since it often isn't resolved until kickoff.
ALERT_STATUSES = {"QUESTIONABLE", "DOUBTFUL", "OUT", "INJURY_RESERVE", "SUSPENSION"}
# How many waiver-wire replacements to suggest per alert.
REPLACEMENTS_PER_ALERT = 3


def _severity(status: str, is_bye: bool) -> int:
    if is_bye:
        return 2
    return {"INJURY_RESERVE": 4, "SUSPENSION": 4, "OUT": 4, "DOUBTFUL": 3, "QUESTIONABLE": 1}.get(status, 0)


def get_roster_alerts(db: Session, league_id: int, my_team_id: int) -> dict:
    league = db.get(League, league_id)
    team = db.query(Team).filter(Team.league_id == league_id, Team.espn_team_id == my_team_id).first()
    if league is None or team is None:
        return {"error": "team_not_found"}

    entries = (
        db.query(RosterEntry)
        .filter(RosterEntry.team_id == team.id)
        .join(Player, RosterEntry.player_id == Player.id)
        .all()
    )

    week = league.current_week or 1
    # A team missing from this week's schedule is on bye — the other way a
    # starting slot quietly goes to zero.
    this_week_schedule = league.schedule or {}
    schedule_known = bool(this_week_schedule)

    flagged = []
    for entry in entries:
        player = entry.player
        is_bye = (
            schedule_known
            and bool(player.pro_team_id)
            and str(player.pro_team_id) not in this_week_schedule
            and player.position != "D/ST"
        )
        if player.injury_status not in ALERT_STATUSES and not is_bye:
            continue
        # A bench player who's hurt isn't a decision you need to make now.
        if not entry.is_starter and player.injury_status == "QUESTIONABLE":
            continue
        flagged.append((entry, player, is_bye))

    if not flagged:
        return {"team": team.name, "week": week, "alerts": []}

    depth_charts = compute_depth_charts(db, league_id)
    free_agents_by_position = _free_agents_by_position(db, league_id)

    alerts = []
    for entry, player, is_bye in flagged:
        alerts.append(
            {
                "player": {
                    "espn_player_id": player.espn_player_id,
                    "name": player.full_name,
                    "position": player.position,
                    "pro_team": pro_team_abbr(player.pro_team_id),
                    "slot": entry.lineup_slot,
                    "is_starter": entry.is_starter,
                    "injury_status": player.injury_status,
                    "projected_points": player.projected_points,
                },
                "reason": "on bye" if is_bye else player.injury_status,
                "severity": _severity(player.injury_status, is_bye),
                "backup": _nfl_backup(depth_charts, player, team.id),
                "replacements": free_agents_by_position.get(player.position, [])[:REPLACEMENTS_PER_ALERT],
            }
        )

    alerts.sort(key=lambda a: (a["severity"], a["player"]["is_starter"]), reverse=True)
    return {"team": team.name, "week": week, "alerts": alerts}


def _nfl_backup(depth_charts: dict, player: Player, my_team_row_id: int) -> dict | None:
    """The next player down the same NFL team's depth chart — who'd absorb
    this player's touches if they sit."""
    chart = depth_charts.get(pro_team_abbr(player.pro_team_id), {}).get(player.position, [])
    entry = next((e for e in chart if e["espn_player_id"] == player.espn_player_id), None)
    if entry is None:
        return None
    backup = next((e for e in chart if e["depth_rank"] == entry["depth_rank"] + 1), None)
    if backup is None:
        return None
    if backup["is_free_agent"]:
        status = "free_agent"
    elif backup["owner_team_id"] == my_team_row_id:
        status = "mine"
    else:
        status = "rostered"
    return {**backup, "status": status}


def _free_agents_by_position(db: Session, league_id: int) -> dict[str, list[dict]]:
    """Best available free agent at each position by this week's
    projection — the realistic replacement pool for an alert."""
    free_agents = (
        db.query(Player)
        .filter(Player.league_id == league_id, Player.is_free_agent.is_(True))
        .all()
    )
    by_position: dict[str, list[Player]] = {}
    for player in free_agents:
        by_position.setdefault(player.position, []).append(player)

    result: dict[str, list[dict]] = {}
    for position, players in by_position.items():
        players.sort(key=lambda p: (p.projected_points if p.projected_points is not None else -1), reverse=True)
        result[position] = [
            {
                "espn_player_id": p.espn_player_id,
                "name": p.full_name,
                "position": p.position,
                "pro_team": pro_team_abbr(p.pro_team_id),
                "projected_points": p.projected_points,
                "percent_owned": p.percent_owned,
                "injury_status": p.injury_status,
            }
            for p in players
        ]
    return result
