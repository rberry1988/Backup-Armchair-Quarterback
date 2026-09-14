from __future__ import annotations

import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class League(Base):
    __tablename__ = "leagues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # ESPN league id
    season: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String, default="")
    current_week: Mapped[int] = mapped_column(Integer, default=1)
    scoring_rules: Mapped[list] = mapped_column(JSON, default=list)
    roster_slot_counts: Mapped[dict] = mapped_column(JSON, default=dict)
    my_team_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    synced_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)

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
