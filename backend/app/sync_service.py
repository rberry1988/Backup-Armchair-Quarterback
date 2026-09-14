from __future__ import annotations

import datetime

from sqlalchemy.orm import Session

from app.espn_client import ESPNClient
from app.espn_constants import is_bench_slot, lineup_slot_label, position_from_id
from app.models import League, Player, RosterEntry, Team
from app.scoring import build_scoring_rules, extract_player_core, player_points_for_week


def _team_name(team_json: dict) -> str:
    name = team_json.get("name")
    if name:
        return name
    return f"{team_json.get('location', '')} {team_json.get('nickname', '')}".strip() or (
        f"Team {team_json.get('id')}"
    )


def sync_league(db: Session, league_id: int, season: int) -> League:
    client = ESPNClient(league_id=league_id, season=season)
    data = client.get_league()

    week = data.get("status", {}).get("latestScoringPeriod") or data.get("scoringPeriodId", 1)
    settings_json = data.get("settings", {})
    scoring_rules = build_scoring_rules(data)
    roster_slot_counts = settings_json.get("rosterSettings", {}).get("lineupSlotCounts", {})

    league = db.get(League, league_id)
    if league is None:
        league = League(id=league_id)
        db.add(league)
    league.season = season
    league.name = settings_json.get("name", f"League {league_id}")
    league.current_week = week
    league.scoring_rules = scoring_rules
    league.roster_slot_counts = roster_slot_counts
    league.synced_at = datetime.datetime.utcnow()
    db.flush()

    # Wipe and rebuild teams/players/rosters for this league — simplest
    # correct approach for a single-user personal app synced on demand.
    db.query(RosterEntry).filter(
        RosterEntry.team_id.in_(db.query(Team.id).filter(Team.league_id == league_id))
    ).delete(synchronize_session=False)
    db.query(Player).filter(Player.league_id == league_id).delete(synchronize_session=False)
    db.query(Team).filter(Team.league_id == league_id).delete(synchronize_session=False)
    db.flush()

    player_by_espn_id: dict[int, Player] = {}

    for team_json in data.get("teams", []):
        record = team_json.get("record", {}).get("overall", {})
        team = Team(
            espn_team_id=team_json["id"],
            league_id=league_id,
            name=_team_name(team_json),
            abbrev=team_json.get("abbrev", ""),
            wins=record.get("wins", 0),
            losses=record.get("losses", 0),
            ties=record.get("ties", 0),
            points_for=record.get("pointsFor", 0.0),
            points_against=record.get("pointsAgainst", 0.0),
        )
        db.add(team)
        db.flush()

        for entry in team_json.get("roster", {}).get("entries", []):
            player_json = entry.get("playerPoolEntry", {}).get("player", {})
            espn_player_id = player_json.get("id")
            if espn_player_id is None:
                continue

            player = player_by_espn_id.get(espn_player_id)
            if player is None:
                core = extract_player_core(player_json)
                projected, actual = player_points_for_week(player_json, week)
                player = Player(
                    espn_player_id=espn_player_id,
                    league_id=league_id,
                    full_name=core["full_name"] or "Unknown",
                    position=position_from_id(core["default_position_id"]),
                    pro_team_id=core["pro_team_id"] or 0,
                    injury_status=core["injury_status"],
                    percent_owned=core["percent_owned"],
                    percent_started=core["percent_started"],
                    eligible_slots=core["eligible_slots"],
                    projected_points=projected,
                    actual_points=actual,
                    is_free_agent=False,
                )
                db.add(player)
                db.flush()
                player_by_espn_id[espn_player_id] = player
            else:
                player.is_free_agent = False

            slot_id = entry.get("lineupSlotId", 20)
            db.add(
                RosterEntry(
                    team_id=team.id,
                    player_id=player.id,
                    lineup_slot_id=slot_id,
                    lineup_slot=lineup_slot_label(slot_id),
                    is_starter=not is_bench_slot(slot_id),
                )
            )

    db.flush()

    # Free agents / waiver wire, so waiver recommendations have someone to suggest.
    free_agents = client.get_free_agents(scoring_period_id=week)
    for entry in free_agents:
        player_json = entry.get("player", entry)
        espn_player_id = player_json.get("id")
        if espn_player_id is None or espn_player_id in player_by_espn_id:
            continue
        core = extract_player_core(player_json)
        projected, actual = player_points_for_week(player_json, week)
        player = Player(
            espn_player_id=espn_player_id,
            league_id=league_id,
            full_name=core["full_name"] or "Unknown",
            position=position_from_id(core["default_position_id"]),
            pro_team_id=core["pro_team_id"] or 0,
            injury_status=core["injury_status"],
            percent_owned=core["percent_owned"],
            percent_started=core["percent_started"],
            eligible_slots=core["eligible_slots"],
            projected_points=projected,
            actual_points=actual,
            is_free_agent=True,
        )
        db.add(player)
        player_by_espn_id[espn_player_id] = player

    db.commit()
    db.refresh(league)
    return league
