from __future__ import annotations

import datetime

from sqlalchemy.orm import Session

from app.espn_client import ESPNClient, fetch_week_schedule
from app.espn_constants import is_bench_slot, lineup_slot_label, position_from_id
from app.models import League, Player, PlayerWeekStat, RosterEntry, Team
from app.scoring import all_weekly_data, build_scoring_rules, extract_player_core, player_points_for_week


def _team_name(team_json: dict) -> str:
    name = team_json.get("name")
    if name:
        return name
    return f"{team_json.get('location', '')} {team_json.get('nickname', '')}".strip() or (
        f"Team {team_json.get('id')}"
    )


def sync_league(db: Session, user_id: int, espn_league_id: int, season: int) -> League:
    client = ESPNClient(league_id=espn_league_id, season=season)
    data = client.get_league()

    week = data.get("status", {}).get("latestScoringPeriod") or data.get("scoringPeriodId", 1)
    settings_json = data.get("settings", {})
    scoring_rules = build_scoring_rules(data)
    roster_slot_counts = settings_json.get("rosterSettings", {}).get("lineupSlotCounts", {})

    league = (
        db.query(League)
        .filter(League.user_id == user_id, League.espn_league_id == espn_league_id, League.season == season)
        .first()
    )
    if league is None:
        league = League(user_id=user_id, espn_league_id=espn_league_id, season=season)
        db.add(league)
    league.name = settings_json.get("name", f"League {espn_league_id}")
    league.current_week = week
    league.scoring_rules = scoring_rules
    league.roster_slot_counts = roster_slot_counts
    league.synced_at = datetime.datetime.utcnow()
    db.flush()
    league_id = league.id

    # Weekly stat snapshots accumulate across syncs (unlike Team/Player
    # below) so trend/rest-of-season features have history to work with.
    existing_week_stats = {
        (row.espn_player_id, row.week): row
        for row in db.query(PlayerWeekStat).filter(PlayerWeekStat.league_id == league_id).all()
    }

    def record_weekly_stats(espn_player_id: int, full_name: str, position: str, player_json: dict) -> None:
        now = datetime.datetime.utcnow()
        for wk, data in all_weekly_data(player_json).items():
            key = (espn_player_id, wk)
            row = existing_week_stats.get(key)
            if row is None:
                row = PlayerWeekStat(
                    league_id=league_id,
                    espn_player_id=espn_player_id,
                    full_name=full_name,
                    position=position,
                    week=wk,
                )
                db.add(row)
                existing_week_stats[key] = row
            if data.get("projected") is not None:
                row.projected_points = data["projected"]
            if data.get("actual") is not None:
                row.actual_points = data["actual"]
            if data.get("raw_stats_actual"):
                row.raw_stats_actual = data["raw_stats_actual"]
            if data.get("raw_stats_projected"):
                row.raw_stats_projected = data["raw_stats_projected"]
            row.full_name = full_name
            row.position = position
            row.captured_at = now

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
                position = position_from_id(core["default_position_id"])
                full_name = core["full_name"] or "Unknown"
                projected, actual = player_points_for_week(player_json, week)
                player = Player(
                    espn_player_id=espn_player_id,
                    league_id=league_id,
                    full_name=full_name,
                    position=position,
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
                record_weekly_stats(espn_player_id, full_name, position, player_json)
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
        position = position_from_id(core["default_position_id"])
        full_name = core["full_name"] or "Unknown"
        projected, actual = player_points_for_week(player_json, week)
        player = Player(
            espn_player_id=espn_player_id,
            league_id=league_id,
            full_name=full_name,
            position=position,
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
        record_weekly_stats(espn_player_id, full_name, position, player_json)

    # Matchup-difficulty inputs: this week's NFL schedule, and every team
    # defense's projected fantasy score (used as a defense-strength proxy).
    # Best-effort — fetch_week_schedule() returns {} on failure rather than
    # raising, so a schedule-API outage never breaks the league sync.
    league.schedule = fetch_week_schedule(week, season)
    league.dst_projected_points = {
        str(player.pro_team_id): player.projected_points
        for player in player_by_espn_id.values()
        if player.position == "D/ST" and player.projected_points is not None and player.pro_team_id
    }

    db.commit()
    db.refresh(league)
    return league
