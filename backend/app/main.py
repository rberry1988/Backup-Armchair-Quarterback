from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.db import get_db, init_db
from app.espn_client import ESPNClientError
from app.models import League, RosterEntry, Team
from app.recommendations.start_sit import get_start_sit
from app.recommendations.trades import get_trade_suggestions
from app.recommendations.waivers import get_waiver_targets
from app.schemas import SetMyTeamRequest, SyncRequest
from app.sync_service import sync_league

app = FastAPI(title="Fantasy Football Copilot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()


def _league_or_404(db: Session, league_id: int) -> League:
    league = db.get(League, league_id)
    if league is None:
        raise HTTPException(status_code=404, detail="League not synced yet. POST /api/sync first.")
    return league


def _require_my_team(league: League) -> int:
    if league.my_team_id is None:
        raise HTTPException(status_code=400, detail="Set your team first via POST /api/league/{id}/my-team")
    return league.my_team_id


@app.post("/api/sync")
def sync(payload: SyncRequest, db: Session = Depends(get_db)):
    try:
        league = sync_league(db, league_id=payload.league_id, season=payload.season)
    except ESPNClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _league_summary(db, league)


def _league_summary(db: Session, league: League) -> dict:
    teams = db.query(Team).filter(Team.league_id == league.id).order_by(Team.name).all()
    return {
        "id": league.id,
        "season": league.season,
        "name": league.name,
        "current_week": league.current_week,
        "scoring_rules": league.scoring_rules,
        "my_team_id": league.my_team_id,
        "synced_at": league.synced_at,
        "teams": [
            {
                "id": t.espn_team_id,
                "name": t.name,
                "abbrev": t.abbrev,
                "wins": t.wins,
                "losses": t.losses,
                "ties": t.ties,
                "points_for": t.points_for,
                "points_against": t.points_against,
            }
            for t in teams
        ],
    }


@app.get("/api/league/{league_id}")
def get_league(league_id: int, db: Session = Depends(get_db)):
    league = _league_or_404(db, league_id)
    return _league_summary(db, league)


@app.post("/api/league/{league_id}/my-team")
def set_my_team(league_id: int, payload: SetMyTeamRequest, db: Session = Depends(get_db)):
    league = _league_or_404(db, league_id)
    team = (
        db.query(Team)
        .filter(Team.league_id == league_id, Team.espn_team_id == payload.team_id)
        .first()
    )
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found in this league")
    league.my_team_id = payload.team_id
    db.commit()
    return _league_summary(db, league)


@app.get("/api/league/{league_id}/roster")
def get_roster(league_id: int, db: Session = Depends(get_db)):
    league = _league_or_404(db, league_id)
    my_team_id = _require_my_team(league)
    team = db.query(Team).filter(Team.league_id == league_id, Team.espn_team_id == my_team_id).first()
    entries = db.query(RosterEntry).filter(RosterEntry.team_id == team.id).all()
    return {
        "team": team.name,
        "week": league.current_week,
        "roster": [
            {
                "name": e.player.full_name,
                "position": e.player.position,
                "slot": e.lineup_slot,
                "is_starter": e.is_starter,
                "projected_points": e.player.projected_points,
                "actual_points": e.player.actual_points,
                "injury_status": e.player.injury_status,
                "percent_owned": e.player.percent_owned,
            }
            for e in entries
        ],
    }


@app.get("/api/league/{league_id}/start-sit")
def start_sit(league_id: int, db: Session = Depends(get_db)):
    league = _league_or_404(db, league_id)
    my_team_id = _require_my_team(league)
    return get_start_sit(db, league_id, my_team_id)


@app.get("/api/league/{league_id}/waivers")
def waivers(league_id: int, db: Session = Depends(get_db)):
    league = _league_or_404(db, league_id)
    my_team_id = _require_my_team(league)
    return get_waiver_targets(db, league_id, my_team_id)


@app.get("/api/league/{league_id}/trades")
def trades(league_id: int, db: Session = Depends(get_db)):
    league = _league_or_404(db, league_id)
    my_team_id = _require_my_team(league)
    return get_trade_suggestions(db, league_id, my_team_id)
