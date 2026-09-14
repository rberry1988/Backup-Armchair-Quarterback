from __future__ import annotations

import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Boolean, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )

    leagues: Mapped[list["League"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class League(Base):
    __tablename__ = "leagues"
    __table_args__ = (UniqueConstraint("user_id", "espn_league_id", "season", name="uq_user_league_season"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    espn_league_id: Mapped[int] = mapped_column(Integer)
    season: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String, default="")
    current_week: Mapped[int] = mapped_column(Integer, default=1)
    scoring_rules: Mapped[list] = mapped_column(JSON, default=list)
    roster_slot_counts: Mapped[dict] = mapped_column(JSON, default=dict)
    my_team_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    synced_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    # This week's NFL schedule: {str(pro_team_id): {abbreviation, opponent_id,
    # opponent_abbreviation}}, and each team's D/ST projected fantasy points
    # ({str(pro_team_id): points}), used together as a matchup-difficulty
    # proxy (see app/matchup.py). Best-effort — empty if ESPN's schedule
    # endpoint was unreachable at sync time.
    schedule: Mapped[dict] = mapped_column(JSON, default=dict)
    dst_projected_points: Mapped[dict] = mapped_column(JSON, default=dict)
    # Real average PPR fantasy points allowed per game, by team abbreviation
    # then position: {"BUF": {"WR": 24.1, "RB": 18.3, ...}, ...}, computed
    # from nflverse's weekly stats. Preferred over dst_projected_points for
    # matchup ratings when available (see app/matchup.py); empty if
    # nflverse was unreachable or the player-id crosswalk had no match.
    points_allowed_by_position: Mapped[dict] = mapped_column(JSON, default=dict)
    # FantasyPros expert consensus rankings: top 10 overall + top 10 per
    # position, for rest-of-season and this week (see
    # app/fantasypros_client.py). Empty unless FANTASYPROS_API_KEY is set;
    # a free-tier key hard-caps this at 10 results per query, so it's only
    # populated for elite/startable players, never full-roster coverage.
    expert_rankings: Mapped[dict] = mapped_column(JSON, default=dict)
    # Whole regular season's NFL matchups, {str(week): {str(pro_team_id):
    # {abbreviation, opponent_id, opponent_abbreviation}}}, and the bye week
    # derived from it per team ({str(pro_team_id): week}). Powers the
    # multi-week schedule outlook and bye planner (app/schedule_outlook.py);
    # `schedule` above stays the current week's copy the matchup tags read.
    season_schedule: Mapped[dict] = mapped_column(JSON, default=dict)
    bye_weeks: Mapped[dict] = mapped_column(JSON, default=dict)
    # What changed between the last two syncs — injury flips, roster moves,
    # ownership swings, projection swings (see app/sync_diff.py), plus the
    # timestamps the comparison spans.
    sync_changes: Mapped[dict] = mapped_column(JSON, default=dict)
    previous_synced_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    # Per-week "points left on bench" history, keyed by ESPN team id then
    # week: {str(espn_team_id): {str(week): {...}}}. Filled lazily by the
    # bench-points endpoint (each past week costs an ESPN boxscore request,
    # so weeks already computed are never re-fetched). See app/bench_points.py.
    bench_points: Mapped[dict] = mapped_column(JSON, default=dict)

    user: Mapped[User] = relationship(back_populates="leagues")
    teams: Mapped[list["Team"]] = relationship(back_populates="league", cascade="all, delete-orphan")


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    espn_team_id: Mapped[int] = mapped_column(Integer)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"))
    name: Mapped[str] = mapped_column(String)
    abbrev: Mapped[str] = mapped_column(String, default="")
    wins: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)
    ties: Mapped[int] = mapped_column(Integer, default=0)
    points_for: Mapped[float] = mapped_column(Float, default=0.0)
    points_against: Mapped[float] = mapped_column(Float, default=0.0)

    league: Mapped[League] = relationship(back_populates="teams")
    roster_entries: Mapped[list["RosterEntry"]] = relationship(
        back_populates="team", cascade="all, delete-orphan"
    )


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    espn_player_id: Mapped[int] = mapped_column(Integer, index=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"))
    full_name: Mapped[str] = mapped_column(String)
    position: Mapped[str] = mapped_column(String)
    pro_team_id: Mapped[int] = mapped_column(Integer, default=0)
    injury_status: Mapped[str] = mapped_column(String, default="ACTIVE")
    percent_owned: Mapped[float] = mapped_column(Float, default=0.0)
    percent_started: Mapped[float] = mapped_column(Float, default=0.0)
    eligible_slots: Mapped[list] = mapped_column(JSON, default=list)
    projected_points: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_points: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_free_agent: Mapped[bool] = mapped_column(Boolean, default=True)

    roster_entries: Mapped[list["RosterEntry"]] = relationship(
        back_populates="player", cascade="all, delete-orphan"
    )


class PlayerWeekStat(Base):
    """A per-week snapshot of a player's projected/actual points.

    Unlike Player (which is wiped and rebuilt on every sync since it
    reflects "right now"), rows here accumulate across syncs so the app
    can show trends and compute rest-of-season averages. Keyed by
    (league_id, espn_player_id, week) rather than Player.id since Player
    rows don't persist identity across syncs.
    """

    __tablename__ = "player_week_stats"
    __table_args__ = (UniqueConstraint("league_id", "espn_player_id", "week", name="uq_league_player_week"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"))
    espn_player_id: Mapped[int] = mapped_column(Integer, index=True)
    full_name: Mapped[str] = mapped_column(String)
    position: Mapped[str] = mapped_column(String)
    week: Mapped[int] = mapped_column(Integer)
    projected_points: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_points: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Raw usage/opportunity counts (targets, carries, receptions, ...) for
    # this week, keyed by short name — see TRACKED_RAW_STAT_IDS in
    # scoring.py. "actual" is what happened; "projected" is ESPN's
    # near-term expectation, useful for an upcoming week with no actual yet.
    raw_stats_actual: Mapped[dict] = mapped_column(JSON, default=dict)
    raw_stats_projected: Mapped[dict] = mapped_column(JSON, default=dict)
    # Advanced metrics nflverse has that ESPN doesn't: target_share,
    # air_yards_share, wopr (all %/ratio, already scaled to human-readable
    # numbers), air_yards, yards_after_catch, snap_pct. See
    # app/advanced_stats.py. Empty if the player has no crosswalk match.
    advanced_stats: Mapped[dict] = mapped_column(JSON, default=dict)
    captured_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)


class RosterEntry(Base):
    __tablename__ = "roster_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    lineup_slot_id: Mapped[int] = mapped_column(Integer)
    lineup_slot: Mapped[str] = mapped_column(String)
    is_starter: Mapped[bool] = mapped_column(Boolean, default=False)

    team: Mapped[Team] = relationship(back_populates="roster_entries")
    player: Mapped[Player] = relationship(back_populates="roster_entries")
