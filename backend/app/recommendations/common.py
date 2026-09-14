from __future__ import annotations

from sqlalchemy.orm import Session, selectinload

from app.models import Player, RosterEntry, Team

INJURED_OUT_STATUSES = {"OUT", "INJURY_RESERVE", "SUSPENSION", "DOUBTFUL"}


def points_or_default(player: Player, default: float = 0.0) -> float:
    return player.projected_points if player.projected_points is not None else default


def get_my_team(db: Session, league_id: int, my_team_id: int) -> Team | None:
    return (
        db.query(Team)
        .filter(Team.league_id == league_id, Team.espn_team_id == my_team_id)
        .first()
    )


def roster_with_players(db: Session, team_id: int) -> list[RosterEntry]:
    """Roster entries with their Player preloaded.

    selectinload (not a plain join) is the point here: joining only filters
    the rows, it doesn't populate the relationship, so every `entry.player`
    would otherwise fire its own SELECT — one per roster spot, on every
    caller of this helper.
    """
    return (
        db.query(RosterEntry)
        .filter(RosterEntry.team_id == team_id)
        .options(selectinload(RosterEntry.player))
        .all()
    )
