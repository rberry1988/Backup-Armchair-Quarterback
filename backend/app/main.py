from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import create_access_token, get_current_user, hash_password, verify_password
from app.db import get_db, init_db
from app.espn_client import ESPNClientError
from app.models import League, RosterEntry, Team, User
from app.recommendations.start_sit import get_start_sit
from app.recommendations.trades import get_trade_suggestions, grade_trade
from app.recommendations.waivers import get_waiver_targets
from app.schemas import (
    LoginRequest,
    RegisterRequest,
    SetMyTeamRequest,
    SyncRequest,
    TokenResponse,
    TradeGradeRequest,
)
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


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


@app.post("/api/auth/register", response_model=TokenResponse)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    user = User(email=payload.email.lower(), hashed_password=hash_password(payload.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with that email already exists") from exc
    db.refresh(user)
    return TokenResponse(access_token=create_access_token(user.id))


@app.post("/api/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email.lower()).first()
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    return TokenResponse(access_token=create_access_token(user.id))


@app.get("/api/auth/me")
def me(current_user: User = Depends(get_current_user)):
    return {"id": current_user.id, "email": current_user.email}


# ---------------------------------------------------------------------------
# Leagues (all scoped to the authenticated user)
# ---------------------------------------------------------------------------


def _owned_league_or_404(db: Session, league_id: int, current_user: User) -> League:
    league = db.get(League, league_id)
    if league is None or league.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="League not found")
    return league


def _require_my_team(league: League) -> int:
    if league.my_team_id is None:
        raise HTTPException(status_code=400, detail="Set your team first via POST /api/league/{id}/my-team")
    return league.my_team_id


def _league_summary(db: Session, league: League) -> dict:
    teams = db.query(Team).filter(Team.league_id == league.id).order_by(Team.name).all()
    return {
        "id": league.id,
        "espn_league_id": league.espn_league_id,
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


@app.get("/api/leagues")
def list_leagues(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    leagues = (
        db.query(League)
        .filter(League.user_id == current_user.id)
        .order_by(League.synced_at.desc())
        .all()
    )
    return [_league_summary(db, league) for league in leagues]


@app.post("/api/sync")
def sync(
    payload: SyncRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        league = sync_league(db, user_id=current_user.id, espn_league_id=payload.league_id, season=payload.season)
    except ESPNClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _league_summary(db, league)


@app.get("/api/league/{league_id}")
def get_league(league_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    league = _owned_league_or_404(db, league_id, current_user)
    return _league_summary(db, league)


@app.post("/api/league/{league_id}/my-team")
def set_my_team(
    league_id: int,
    payload: SetMyTeamRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    league = _owned_league_or_404(db, league_id, current_user)
    team = db.query(Team).filter(Team.league_id == league.id, Team.espn_team_id == payload.team_id).first()
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found in this league")
    league.my_team_id = payload.team_id
    db.commit()
    return _league_summary(db, league)


@app.get("/api/league/{league_id}/roster")
def get_roster(league_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    league = _owned_league_or_404(db, league_id, current_user)
    my_team_id = _require_my_team(league)
    team = db.query(Team).filter(Team.league_id == league.id, Team.espn_team_id == my_team_id).first()
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
def start_sit(league_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    league = _owned_league_or_404(db, league_id, current_user)
    my_team_id = _require_my_team(league)
    return get_start_sit(db, league.id, my_team_id)


@app.get("/api/league/{league_id}/waivers")
def waivers(league_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    league = _owned_league_or_404(db, league_id, current_user)
    my_team_id = _require_my_team(league)
    return get_waiver_targets(db, league.id, my_team_id)


@app.get("/api/league/{league_id}/trades")
def trades(league_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    league = _owned_league_or_404(db, league_id, current_user)
    my_team_id = _require_my_team(league)
    return get_trade_suggestions(db, league.id, my_team_id)


@app.get("/api/league/{league_id}/teams-with-rosters")
def teams_with_rosters(
    league_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    league = _owned_league_or_404(db, league_id, current_user)
    teams = db.query(Team).filter(Team.league_id == league.id).order_by(Team.name).all()
    result = []
    for team in teams:
        entries = db.query(RosterEntry).filter(RosterEntry.team_id == team.id).all()
        result.append(
            {
                "id": team.espn_team_id,
                "name": team.name,
                "roster": [
                    {
                        "espn_player_id": e.player.espn_player_id,
                        "name": e.player.full_name,
                        "position": e.player.position,
                        "projected_points": e.player.projected_points,
                    }
                    for e in entries
                ],
            }
        )
    return result


@app.post("/api/league/{league_id}/trade-grade")
def trade_grade(
    league_id: int,
    payload: TradeGradeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    league = _owned_league_or_404(db, league_id, current_user)
    result = grade_trade(
        db,
        league.id,
        team_a_espn_id=payload.team_a_id,
        team_a_sends=payload.team_a_sends,
        team_b_espn_id=payload.team_b_id,
        team_b_sends=payload.team_b_sends,
    )
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result
