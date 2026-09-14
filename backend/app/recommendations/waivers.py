from __future__ import annotations

from sqlalchemy.orm import Session

from app.matchup import get_matchup_context
from app.models import League, Player
from app.recommendations.common import (
    INJURED_OUT_STATUSES,
    get_my_team,
    points_or_default,
    roster_with_players,
)
from app.trends import get_player_trend

POSITIONS = ["QB", "RB", "WR", "TE", "K", "D/ST"]

# Suggested FAAB bid as a % of a standard 100-point budget, scaled by how
# many points the pickup projects to add over what it replaces. Purely a
# starting-point heuristic — irrelevant if your league uses waiver
# priority instead of FAAB.
def _suggested_faab_pct(point_upgrade: float) -> int:
    return max(0, min(35, round(point_upgrade * 2.5)))


def get_waiver_targets(db: Session, league_id: int, my_team_id: int, top_n: int = 5) -> dict:
    team = get_my_team(db, league_id, my_team_id)
    if team is None:
        return {"error": "team_not_found"}

    league = db.get(League, league_id)

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

    results = []
    for position in POSITIONS:
        my_players = sorted(
            my_players_by_position.get(position, []),
            key=lambda p: points_or_default(p),
            reverse=True,
        )
        weakest_rostered = my_players[-1] if my_players else None
        baseline = points_or_default(weakest_rostered) if weakest_rostered else 0.0

        candidates = [p for p in free_agents if p.position == position and p.injury_status not in INJURED_OUT_STATUSES]
        candidates.sort(key=lambda p: points_or_default(p), reverse=True)

        upgrades = []
        for candidate in candidates[: top_n * 2]:
            candidate_points = points_or_default(candidate)
            if weakest_rostered is None or candidate_points > baseline:
                point_upgrade = round(candidate_points - baseline, 1)
                upgrades.append(
                    {
                        "add": {
                            "name": candidate.full_name,
                            "projected_points": candidate.projected_points,
                            "percent_owned": round(candidate.percent_owned, 1),
                            "injury_status": candidate.injury_status,
                            "matchup": get_matchup_context(league, candidate.pro_team_id, candidate.position)
                            if league
                            else None,
                            "trend": get_player_trend(db, league_id, candidate.espn_player_id, candidate.position),
                        },
                        "drop_candidate": (
                            {
                                "name": weakest_rostered.full_name,
                                "projected_points": weakest_rostered.projected_points,
                            }
                            if weakest_rostered
                            else None
                        ),
                        "point_upgrade": point_upgrade,
                        "suggested_faab_pct": _suggested_faab_pct(point_upgrade),
                    }
                )
            if len(upgrades) >= top_n:
                break

        if upgrades:
            results.append({"position": position, "suggestions": upgrades})

    return {"team": team.name, "recommendations": results}
