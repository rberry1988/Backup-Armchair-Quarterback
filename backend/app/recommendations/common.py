from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Player, RosterEntry, Team

INJURED_OUT_STATUSES = {"OUT", "INJURY_RESERVE", "SUSPENSION", "DOUBTFUL"}

# Rough map of which positions can fill each ESPN lineup slot id.
SLOT_ELIGIBLE_POSITIONS = {
    0: {"QB"},
    2: {"RB"},
    3: {"RB", "WR"},
    4: {"WR"},
    5: {"WR", "TE"},
    6: {"TE"},
    7: {"QB", "RB", "WR", "TE"},
    16: {"D/ST"},
    17: {"K"},
    23: {"RB", "WR", "TE"},
}


def points_or_default(player: Player, default: float = 0.0) -> float:
    return player.projected_points if player.projected_points is not None else default


def get_my_team(db: Session, league_id: int, my_team_id: int) -> Team | None:
    return (
        db.query(Team)
        .filter(Team.league_id == league_id, Team.espn_team_id == my_team_id)
        .first()
    )


def roster_with_players(db: Session, team_id: int) -> list[RosterEntry]:
    return (
        db.query(RosterEntry)
        .filter(RosterEntry.team_id == team_id)
        .join(Player)
        .all()
    )
