from __future__ import annotations

import datetime
import logging

from sqlalchemy.orm import Session

from app.advanced_stats import (
    compute_defense_vs_position,
    compute_points_allowed_by_position,
    get_advanced_stats_for_player,
    index_snaps_by_pfr,
    index_weekly_by_gsis,
)
from app.app_settings import get_fantasypros_api_key
from app.espn_client import (
    ESPNClient,
    ESPNClientError,
    compute_bye_weeks,
    fetch_season_schedule,
    fetch_week_schedule,
)
from app.espn_constants import is_bench_slot, lineup_slot_label, position_from_id
from app.espn_league_settings import (
    acquisition_settings,
    fantasy_schedule,
    team_acquisition_state,
)
from app.fantasycalc_client import fetch_player_values, num_qbs_from_roster_slots, ppr_from_scoring_rules
from app.fantasypros_client import fetch_expert_rankings_bundle, fetch_injury_context, infer_scoring_format
from app.league_activity import build_activity, parse_transactions
from app.models import League, Player, PlayerWeekStat, RosterEntry, Team
from app.nflverse_client import fetch_id_crosswalk, fetch_snap_counts, fetch_weekly_player_stats
from app.scoring import all_weekly_data, build_scoring_rules, extract_player_core
from app.sync_diff import diff_players, snapshot_players

logger = logging.getLogger(__name__)


def _team_name(team_json: dict) -> str:
    name = team_json.get("name")
    if name:
        return name
    return f"{team_json.get('location', '')} {team_json.get('nickname', '')}".strip() or (
        f"Team {team_json.get('id')}"
    )


def sync_league(
    db: Session,
    user_id: int,
    espn_league_id: int,
    season: int,
    espn_s2: str | None = None,
    espn_swid: str | None = None,
) -> League:
    """`espn_s2`/`espn_swid` are the syncing user's own ESPN cookies when
    they've saved them (see User.espn_s2). Passing them lets someone sync a
    private league of their own without the operator's instance-wide
    credentials — and without those credentials being used to read a league
    the requester has no access to, which is the risk /api/sync guards
    against when they aren't set."""
    client = ESPNClient(
        league_id=espn_league_id, season=season, espn_s2=espn_s2, espn_swid=espn_swid
    )
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
    acquisition = acquisition_settings(data)
    league.uses_faab = acquisition["uses_faab"]
    league.acquisition_budget = acquisition["budget"]
    league.fantasy_schedule = fantasy_schedule(data)
    previous_synced_at = league.synced_at
    league.synced_at = datetime.datetime.utcnow()
    db.flush()
    league_id = league.id

    # Snapshot the outgoing player pool before the wipe below, so the
    # rebuilt one can be diffed against it into a "what changed" digest.
    previous_players = snapshot_players(db, league_id) if previous_synced_at else {}

    # Weekly stat snapshots accumulate across syncs (unlike Team/Player
    # below) so trend/rest-of-season features have history to work with.
    existing_week_stats = {
        (row.espn_player_id, row.week): row
        for row in db.query(PlayerWeekStat).filter(PlayerWeekStat.league_id == league_id).all()
    }

    def record_weekly_stats(espn_player_id: int, full_name: str, position: str, weekly_data: dict[int, dict]) -> None:
        now = datetime.datetime.utcnow()
        for wk, data in weekly_data.items():
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
        acquisition_state = team_acquisition_state(team_json)
        team = Team(
            espn_team_id=team_json.get("id"),
            league_id=league_id,
            name=_team_name(team_json),
            abbrev=team_json.get("abbrev", ""),
            faab_spent=acquisition_state["faab_spent"],
            waiver_rank=acquisition_state["waiver_rank"],
            acquisitions=acquisition_state["acquisitions"],
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
                weekly_data = all_weekly_data(player_json)
                current_week_data = weekly_data.get(week, {})
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
                    projected_points=current_week_data.get("projected"),
                    actual_points=current_week_data.get("actual"),
                    is_free_agent=False,
                )
                db.add(player)
                db.flush()
                player_by_espn_id[espn_player_id] = player
                record_weekly_stats(espn_player_id, full_name, position, weekly_data)
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
        weekly_data = all_weekly_data(player_json)
        current_week_data = weekly_data.get(week, {})
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
            projected_points=current_week_data.get("projected"),
            actual_points=current_week_data.get("actual"),
            is_free_agent=True,
        )
        db.add(player)
        player_by_espn_id[espn_player_id] = player
        record_weekly_stats(espn_player_id, full_name, position, weekly_data)

    db.flush()

    # Diff the rebuilt player pool against the pre-wipe snapshot into the
    # "what changed since last sync" digest (app/sync_diff.py).
    if previous_players:
        league.previous_synced_at = previous_synced_at
        league.sync_changes = {
            "since": previous_synced_at.isoformat() if previous_synced_at else None,
            "at": league.synced_at.isoformat(),
            "items": diff_players(previous_players, snapshot_players(db, league_id)),
        }

    # Matchup-difficulty inputs: this week's NFL schedule, and every team
    # defense's projected fantasy score (used as a defense-strength proxy
    # fallback when real points-allowed data below isn't available).
    # Best-effort — fetch_week_schedule() returns {} on failure rather than
    # raising, so a schedule-API outage never breaks the league sync.
    league.schedule = fetch_week_schedule(week, season)
    league.dst_projected_points = {
        str(player.pro_team_id): player.projected_points
        for player in player_by_espn_id.values()
        if player.position == "D/ST" and player.projected_points is not None and player.pro_team_id
    }

    # The whole season's matchups (cached on disk for a day) drive the
    # multi-week outlook and bye planner. Keep whatever was stored last
    # sync if this fetch came back empty, rather than blanking those tabs.
    season_schedule = fetch_season_schedule(season)
    if season_schedule:
        league.season_schedule = {
            str(wk): {str(tid): info for tid, info in teams.items()} for wk, teams in season_schedule.items()
        }
        league.bye_weeks = {str(tid): bye for tid, bye in compute_bye_weeks(season_schedule).items()}

    # Advanced stats nflverse has that ESPN doesn't (target share, air
    # yards share, WOPR, snap %), plus real points-allowed-by-position —
    # all best-effort, joined to our ESPN players via the dynastyprocess
    # id crosswalk. Any empty result here just means these enrichments are
    # skipped this sync; it never blocks the ESPN data above.
    crosswalk = fetch_id_crosswalk()
    weekly_stats_rows = fetch_weekly_player_stats(season) if crosswalk else []
    if crosswalk and weekly_stats_rows:
        gsis_index = index_weekly_by_gsis(weekly_stats_rows)
        pfr_index = index_snaps_by_pfr(fetch_snap_counts(season))
        now = datetime.datetime.utcnow()
        for espn_player_id, player in player_by_espn_id.items():
            adv_by_week = get_advanced_stats_for_player(espn_player_id, crosswalk, gsis_index, pfr_index)
            for wk, adv_stats in adv_by_week.items():
                key = (espn_player_id, wk)
                row = existing_week_stats.get(key)
                if row is None:
                    row = PlayerWeekStat(
                        league_id=league_id,
                        espn_player_id=espn_player_id,
                        full_name=player.full_name,
                        position=player.position,
                        week=wk,
                    )
                    db.add(row)
                    existing_week_stats[key] = row
                row.advanced_stats = adv_stats
                row.captured_at = now

        league.points_allowed_by_position = compute_points_allowed_by_position(weekly_stats_rows, through_week=week)
        league.defense_vs_position = compute_defense_vs_position(weekly_stats_rows, through_week=week)

    # League transaction log -> the activity feed and per-manager FAAB
    # spending profile (app/league_activity.py). One extra request, wrapped
    # like every other enrichment here: a failure leaves the previous feed
    # in place rather than clobbering it with an empty one, and never fails
    # the sync around it.
    try:
        transaction_data = client.get_transactions()
    except ESPNClientError as exc:
        logger.info("Transaction log unavailable for league %s: %s", league_id, exc)
        transaction_data = None
    if transaction_data is not None:
        try:
            team_names = {t.espn_team_id: t.name for t in db.query(Team).filter(Team.league_id == league_id)}
            # PlayerWeekStat accumulates across syncs, so it remembers
            # players who have since left the pool entirely — exactly the
            # ones a transaction log refers to.
            # .distinct() because this table holds one row per player *per
            # week* — without it a mid-season league hands back thousands of
            # rows to build a few hundred dictionary entries.
            player_names = {
                espn_id: name
                for espn_id, name in db.query(PlayerWeekStat.espn_player_id, PlayerWeekStat.full_name)
                .filter(PlayerWeekStat.league_id == league_id)
                .distinct()
                .all()
            }
            player_names.update({p.espn_player_id: p.full_name for p in player_by_espn_id.values()})
            new_activity = build_activity(parse_transactions(transaction_data), team_names, player_names)
            if new_activity["transactions"]:
                league.activity = new_activity
        except Exception:  # noqa: BLE001 — an undocumented payload must not fail a sync
            logger.exception("Could not build the activity feed for league %s", league_id)

    # FantasyPros expert consensus rankings (top 10 overall + per position,
    # rest-of-season + this week) — optional, only if a key is configured
    # (backend/.env or the Admin tab, see app_settings.get_fantasypros_api_key);
    # fetch_expert_rankings_bundle() returns {} on any failure, in which
    # case we leave whatever was synced last time alone rather than
    # clobbering it with an empty result.
    new_expert_rankings = fetch_expert_rankings_bundle(
        season, week, infer_scoring_format(scoring_rules), crosswalk, get_fantasypros_api_key(db)
    )
    if new_expert_rankings:
        league.expert_rankings = new_expert_rankings

    # FantasyPros full-league injury report — same API key as expert
    # rankings, but not top-10-capped, so this covers every rostered
    # player rather than just elite ones. Best-effort like the rankings
    # fetch above: leave last sync's data alone on an empty result.
    new_fantasypros_injuries = fetch_injury_context(season, week, crosswalk, get_fantasypros_api_key(db))
    if new_fantasypros_injuries:
        league.fantasypros_injuries = {str(pid): injury for pid, injury in new_fantasypros_injuries.items()}

    # FantasyCalc market trade values, scaled to this league's actual format
    # — free API, no key needed, but still best-effort: fetch_player_values()
    # returns {} on any failure, and we leave last sync's values alone
    # rather than clobbering them with an empty result.
    num_teams = len(data.get("teams", []))
    if num_teams:
        new_fantasycalc_values = fetch_player_values(
            num_teams=num_teams,
            ppr=ppr_from_scoring_rules(scoring_rules),
            num_qbs=num_qbs_from_roster_slots(roster_slot_counts),
        )
        if new_fantasycalc_values:
            league.fantasycalc_values = {str(pid): value for pid, value in new_fantasycalc_values.items()}

    db.commit()
    db.refresh(league)
    return league
