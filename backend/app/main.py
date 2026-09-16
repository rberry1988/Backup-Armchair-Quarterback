import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.alerts import get_roster_alerts
from app.app_settings import fantasypros_api_key_source, set_fantasypros_api_key
from app.auto_sync import auto_sync_loop, clamp_interval_hours
from app.auth import (
    check_login_allowed,
    check_registration_allowed,
    clear_failed_logins,
    client_ip,
    create_access_token,
    get_current_user,
    has_premium_access,
    hash_password,
    is_admin,
    is_admin_locked,
    record_failed_login,
    record_registration,
    require_admin,
    require_premium,
    verify_password,
)
from app.bench_points import get_bench_points
from app.config import settings
from app.consistency import get_consistency
from app.db import get_db, init_db
from app.deploy_service import run_update
from app.depth_charts import compute_depth_charts, get_rb_handcuffs
from app.espn_claims import get_pending_claims
from app.espn_client import ESPNClientError, normalize_swid
from app.fantasycalc_client import get_trade_value
from app.fantasypros_client import get_injury_context
from app.models import League, PlannedMove, RosterEntry, Team, User
from app.schedule_outlook import get_schedule_outlook
from app.live_scoring import get_live_matchup
from app.notifications import send_webhook, webhook_url_error
from app.playoff_odds import get_playoff_odds
from app.recommendations.matchup_preview import get_matchup_preview
from app.recommendations.start_sit import get_start_sit
from app.recommendations.trades import get_trade_suggestions, grade_trade
from app.recommendations.waivers import get_waiver_targets
from app.schemas import (
    AdminUserOut,
    AutoSyncRequest,
    ChangePasswordRequest,
    EspnCredentialsRequest,
    EspnCredentialsStatus,
    FantasyProsKeyRequest,
    FantasyProsKeyStatus,
    LoginRequest,
    RegisterRequest,
    PlannedMoveRequest,
    ResetPasswordRequest,
    SetAdminRequest,
    SetMyTeamRequest,
    SetPremiumRequest,
    SyncRequest,
    TokenResponse,
    WebhookRequest,
    WebhookStatus,
    TradeGradeRequest,
    UpdateDisplayNameRequest,
    UserOut,
)
from app.sync_service import sync_league
from app.trends import get_player_trends


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    scheduler = asyncio.create_task(auto_sync_loop())
    try:
        yield
    finally:
        scheduler.cancel()


app = FastAPI(
    title="Backup Armchair Quarterback",
    lifespan=lifespan,
    # Off unless ENABLE_API_DOCS=true — see Settings.enable_api_docs.
    docs_url="/docs" if settings.enable_api_docs else None,
    redoc_url="/redoc" if settings.enable_api_docs else None,
    openapi_url="/openapi.json" if settings.enable_api_docs else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


@app.post("/api/auth/register", response_model=TokenResponse)
def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    check_registration_allowed(ip)
    user = User(email=payload.email.lower(), hashed_password=hash_password(payload.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with that email already exists") from exc
    db.refresh(user)
    record_registration(ip)
    return TokenResponse(access_token=create_access_token(user.id))


@app.post("/api/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    email = payload.email.lower()
    ip = client_ip(request)
    check_login_allowed(email, ip)

    user = db.query(User).filter(User.email == email).first()
    if user is None or not verify_password(payload.password, user.hashed_password):
        record_failed_login(email, ip)
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    clear_failed_logins(email, ip)
    return TokenResponse(access_token=create_access_token(user.id))


def _user_out(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "is_admin": is_admin(user),
        "is_premium": has_premium_access(user),
        "display_name": user.display_name,
    }


@app.get("/api/auth/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return _user_out(current_user)


@app.post("/api/auth/display-name", response_model=UserOut)
def update_display_name(
    payload: UpdateDisplayNameRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    current_user.display_name = payload.display_name or None
    db.commit()
    db.refresh(current_user)
    return _user_out(current_user)


# Connecting an ESPN account is premium: what it unlocks — real pending
# claims — is a premium panel, so the setup for it lives behind the same
# gate. Enforced here and not only by hiding the section in Settings, as
# with every other premium feature.
#
# One consequence worth knowing: an account demoted to basic keeps whatever
# cookies it already saved, and its own syncs keep using them, but it can no
# longer see or clear them from Settings until premium is restored. Leaving
# them in place was the better of the two wrong answers — clearing them on
# demotion would silently break that person's private-league sync.
@app.get("/api/auth/espn-credentials", response_model=EspnCredentialsStatus)
def get_espn_credentials(current_user: User = Depends(require_premium)):
    """Whether this account has ESPN cookies saved. Never returns the
    cookies themselves — see EspnCredentialsStatus."""
    return EspnCredentialsStatus(connected=bool(current_user.espn_s2 and current_user.espn_swid))


@app.post("/api/auth/espn-credentials", response_model=EspnCredentialsStatus)
def set_espn_credentials(
    payload: EspnCredentialsRequest,
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """Save (or clear) this account's own ESPN session cookies.

    These let the app read what ESPN will only show the account they belong
    to — chiefly that user's real pending waiver claims — and let them sync
    their own private leagues without the operator's shared credentials.
    Strictly per-account: nothing here is ever used to serve another user's
    request.
    """
    espn_s2 = payload.espn_s2.strip()
    swid = normalize_swid(payload.swid)
    if not espn_s2 or not swid:
        # Either half missing means "disconnect" — an espn_s2 without its
        # SWID (or the reverse) is not a session ESPN will accept, so
        # storing one alone would only produce confusing 401s later.
        current_user.espn_s2 = None
        current_user.espn_swid = None
        db.commit()
        return EspnCredentialsStatus(connected=False)

    current_user.espn_s2 = espn_s2
    current_user.espn_swid = swid
    db.commit()
    return EspnCredentialsStatus(connected=True)


def _webhook_service(url: str | None) -> str | None:
    if not url:
        return None
    return "Slack" if "slack.com" in url else "Discord"


@app.get("/api/auth/webhook", response_model=WebhookStatus)
def get_webhook(current_user: User = Depends(require_premium)):
    """Whether notifications are on, and which service. Never the URL — a
    webhook URL is a bearer token for posting into someone's channel."""
    return WebhookStatus(
        configured=bool(current_user.webhook_url), service=_webhook_service(current_user.webhook_url)
    )


@app.post("/api/auth/webhook", response_model=WebhookStatus)
def set_webhook(
    payload: WebhookRequest,
    current_user: User = Depends(require_premium),
    db: Session = Depends(get_db),
):
    """Save or clear this account's notification webhook.

    The URL is validated against a host allowlist before it is stored, not
    only before it is used: an unvalidated URL sitting in the database is
    one refactor away from becoming a request the server makes.
    """
    url = payload.webhook_url.strip()
    if not url:
        current_user.webhook_url = None
        db.commit()
        return WebhookStatus(configured=False)

    problem = webhook_url_error(url)
    if problem:
        raise HTTPException(status_code=422, detail=problem)

    current_user.webhook_url = url
    db.commit()
    return WebhookStatus(configured=True, service=_webhook_service(url))


@app.post("/api/auth/webhook/test", status_code=204)
def test_webhook(current_user: User = Depends(require_premium)):
    """Send a message now, so a wrong URL is found here rather than
    discovered as silence on a Sunday morning."""
    if not current_user.webhook_url:
        raise HTTPException(status_code=400, detail="No webhook saved yet.")
    if not send_webhook(
        current_user.webhook_url,
        "**Backup Armchair Quarterback** — notifications are working. "
        "You'll get a message here when a starter is out or on bye, and when your league changes.",
    ):
        raise HTTPException(
            status_code=502,
            detail="That webhook didn't accept the message. Check the URL is still valid in Discord or Slack.",
        )


@app.post("/api/auth/change-password", status_code=204)
def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    current_user.hashed_password = hash_password(payload.new_password)
    db.commit()


# ---------------------------------------------------------------------------
# Admin (managing other accounts on this instance — see Settings.admin_emails)
# ---------------------------------------------------------------------------


def _admin_user_out(u: User, league_count: int) -> AdminUserOut:
    return AdminUserOut(
        id=u.id,
        email=u.email,
        created_at=u.created_at,
        league_count=league_count,
        is_admin=is_admin(u),
        admin_locked=is_admin_locked(u),
        is_premium=u.is_premium,
    )


@app.get("/api/admin/users", response_model=list[AdminUserOut])
def admin_list_users(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    users = db.query(User).order_by(User.created_at).all()
    league_counts = dict(
        db.query(League.user_id, func.count(League.id)).group_by(League.user_id).all()
    )
    return [_admin_user_out(u, league_counts.get(u.id, 0)) for u in users]


@app.post("/api/admin/users", response_model=AdminUserOut, status_code=201)
def admin_create_user(
    payload: RegisterRequest, db: Session = Depends(get_db), _admin: User = Depends(require_admin)
):
    user = User(email=payload.email.lower(), hashed_password=hash_password(payload.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with that email already exists") from exc
    db.refresh(user)
    return _admin_user_out(user, 0)


@app.delete("/api/admin/users/{user_id}", status_code=204)
def admin_delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="You can't remove your own account")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(user)  # cascades to their leagues (see User.leagues relationship)
    db.commit()


@app.post("/api/admin/users/{user_id}/reset-password", status_code=204)
def admin_reset_password(
    user_id: int,
    payload: ResetPasswordRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """The "forgot password" flow for this app: no email/SMTP setup needed,
    an admin just sets a new one directly. See README for why."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    user.hashed_password = hash_password(payload.new_password)
    db.commit()


@app.post("/api/admin/users/{user_id}/admin", response_model=AdminUserOut)
def admin_set_admin(
    user_id: int,
    payload: SetAdminRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Grant or revoke admin access for another account. Layers on top of
    (never replaces) ADMIN_EMAILS — see User.admin_granted and
    auth.is_admin(). Config-listed admins can't be changed here since the
    toggle would have no real effect; edit backend/.env for those."""
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="You can't change your own admin access")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if is_admin_locked(user):
        raise HTTPException(
            status_code=400,
            detail="This account's admin access is set via ADMIN_EMAILS in backend/.env, not toggleable here.",
        )
    user.admin_granted = payload.is_admin
    db.commit()
    db.refresh(user)
    league_count = db.query(func.count(League.id)).filter(League.user_id == user.id).scalar() or 0
    return _admin_user_out(user, league_count)


@app.post("/api/admin/users/{user_id}/premium", response_model=AdminUserOut)
def admin_set_premium(
    user_id: int,
    payload: SetPremiumRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Grant or revoke premium access (currently just the Extra tab) for an
    account — see User.is_premium and auth.has_premium_access()."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_premium = payload.is_premium
    db.commit()
    db.refresh(user)
    league_count = db.query(func.count(League.id)).filter(League.user_id == user.id).scalar() or 0
    return _admin_user_out(user, league_count)


@app.get("/api/admin/fantasypros-key", response_model=FantasyProsKeyStatus)
def get_fantasypros_key_status(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    source = fantasypros_api_key_source(db)
    return FantasyProsKeyStatus(configured=source is not None, source=source)


@app.post("/api/admin/fantasypros-key", response_model=FantasyProsKeyStatus)
def set_fantasypros_key(
    payload: FantasyProsKeyRequest, db: Session = Depends(get_db), _admin: User = Depends(require_admin)
):
    """Saves the Expert Rankings API key for next sync onward (takes
    effect immediately, no restart) — or clears it, falling back to
    FANTASYPROS_API_KEY in backend/.env if that's set. Never echoes the
    key back; see FantasyProsKeyStatus."""
    set_fantasypros_api_key(db, payload.api_key)
    source = fantasypros_api_key_source(db)
    return FantasyProsKeyStatus(configured=source is not None, source=source)


@app.post("/api/admin/update")
def admin_update(_admin: User = Depends(require_admin)):
    if not settings.enable_self_update:
        raise HTTPException(
            status_code=400,
            detail="Self-update is disabled. Set ENABLE_SELF_UPDATE=true in backend/.env to enable it.",
        )
    return run_update()


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
        "auto_sync_enabled": league.auto_sync_enabled,
        "auto_sync_interval_hours": league.auto_sync_interval_hours,
        "auto_synced_at": league.auto_synced_at,
        "auto_sync_error": league.auto_sync_error,
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


@app.delete("/api/league/{league_id}", status_code=204)
def delete_league(league_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Removes a league you've synced — just yours, not anyone else's copy
    of the same ESPN league (see the (user_id, espn_league_id, season)
    uniqueness on League). Cascades to its teams/rosters/players/stat
    history (see the League relationships in models.py)."""
    league = _owned_league_or_404(db, league_id, current_user)
    db.delete(league)
    db.commit()


@app.post("/api/sync")
def sync(
    payload: SyncRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # ESPN_S2/ESPN_SWID are a single operator-configured credential shared
    # by every user of this instance. Once they're set, letting any
    # authenticated (non-admin) user sync an arbitrary league_id would use
    # the operator's own private ESPN session to pull whatever private
    # league that id names into the requester's account — data they have
    # no legitimate access to. Public leagues carry no such risk, so this
    # restriction only kicks in once private-league cookies are in play.
    # A user who has saved their *own* ESPN cookies is exempt: the sync
    # below runs as them, so it can only reach leagues their own ESPN
    # account can already see.
    uses_own_espn_account = bool(current_user.espn_s2 and current_user.espn_swid)
    if settings.espn_s2 and settings.espn_league_id and not is_admin(current_user) and not uses_own_espn_account:
        if payload.league_id != settings.espn_league_id or payload.season != settings.espn_season:
            raise HTTPException(
                status_code=403,
                detail="This instance is configured for one private ESPN league; only an admin can sync a different one.",
            )
    try:
        league = sync_league(
            db,
            user_id=current_user.id,
            espn_league_id=payload.league_id,
            season=payload.season,
            espn_s2=current_user.espn_s2,
            espn_swid=current_user.espn_swid,
        )
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


# ---------------------------------------------------------------------------
# Planned waiver moves (premium)
# ---------------------------------------------------------------------------

# Bounded so a runaway client can't turn this into unbounded storage, and
# because a claim shortlist this long isn't a shortlist any more.
MAX_PLANNED_MOVES_PER_LEAGUE = 25


def _planned_move_out(move: PlannedMove) -> dict:
    return {
        "id": move.id,
        "add_espn_player_id": move.add_espn_player_id,
        "add_name": move.add_name,
        "add_position": move.add_position,
        "drop_espn_player_id": move.drop_espn_player_id,
        "drop_name": move.drop_name,
        "faab_bid": move.faab_bid,
        "note": move.note,
        "created_at": move.created_at,
    }


@app.get("/api/league/{league_id}/planned-moves")
def list_planned_moves(
    league_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_premium),
):
    league = _owned_league_or_404(db, league_id, current_user)
    moves = (
        db.query(PlannedMove)
        .filter(PlannedMove.league_id == league.id)
        .order_by(PlannedMove.created_at)
        .all()
    )
    return [_planned_move_out(m) for m in moves]


@app.post("/api/league/{league_id}/planned-moves", status_code=201)
def add_planned_move(
    league_id: int,
    payload: PlannedMoveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_premium),
):
    league = _owned_league_or_404(db, league_id, current_user)
    existing = db.query(func.count(PlannedMove.id)).filter(PlannedMove.league_id == league.id).scalar() or 0
    if existing >= MAX_PLANNED_MOVES_PER_LEAGUE:
        raise HTTPException(
            status_code=400,
            detail=f"You can plan up to {MAX_PLANNED_MOVES_PER_LEAGUE} moves at a time. Remove one first.",
        )
    already_planned = (
        db.query(PlannedMove)
        .filter(
            PlannedMove.league_id == league.id,
            PlannedMove.add_espn_player_id == payload.add_espn_player_id,
        )
        .first()
    )
    if already_planned is not None:
        raise HTTPException(status_code=409, detail=f"{payload.add_name} is already in your planned moves.")

    move = PlannedMove(league_id=league.id, **payload.model_dump())
    db.add(move)
    db.commit()
    db.refresh(move)
    return _planned_move_out(move)


@app.delete("/api/league/{league_id}/planned-moves/{move_id}", status_code=204)
def delete_planned_move(
    league_id: int,
    move_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_premium),
):
    league = _owned_league_or_404(db, league_id, current_user)
    move = db.get(PlannedMove, move_id)
    # Checked against this league (already proven to be the caller's) rather
    # than trusting the id alone, so a move id from someone else's league
    # can't be deleted by guessing it.
    if move is None or move.league_id != league.id:
        raise HTTPException(status_code=404, detail="Planned move not found")
    db.delete(move)
    db.commit()


@app.get("/api/league/{league_id}/pending-claims")
def list_pending_claims(
    league_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_premium),
):
    """The claims this user has genuinely submitted in ESPN and that ESPN
    hasn't processed yet. Read straight from ESPN on each request rather
    than stored: a claim's whole point is that it's about to change, and a
    stale copy of one is worse than none. See app/espn_claims.py."""
    league = _owned_league_or_404(db, league_id, current_user)
    return get_pending_claims(db, league, current_user)


@app.post("/api/league/{league_id}/auto-sync")
def set_auto_sync(
    league_id: int,
    payload: AutoSyncRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Turn scheduled background re-syncing on/off for one league. The
    scheduler itself lives in app/auto_sync.py."""
    league = _owned_league_or_404(db, league_id, current_user)
    league.auto_sync_enabled = payload.enabled
    league.auto_sync_interval_hours = clamp_interval_hours(payload.interval_hours)
    if not payload.enabled:
        # Nothing is pending any more, so a stale failure from the last run
        # would just sit in the UI misreporting the current state.
        league.auto_sync_error = None
    db.commit()
    return _league_summary(db, league)


@app.get("/api/league/{league_id}/roster")
def get_roster(league_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    league = _owned_league_or_404(db, league_id, current_user)
    my_team_id = _require_my_team(league)
    team = db.query(Team).filter(Team.league_id == league.id, Team.espn_team_id == my_team_id).first()
    entries = (
        db.query(RosterEntry)
        .filter(RosterEntry.team_id == team.id)
        .options(selectinload(RosterEntry.player))
        .all()
    )
    trends = get_player_trends(db, league.id, [(e.player.espn_player_id, e.player.position) for e in entries])
    consistency = get_consistency(db, league.id, [e.player.espn_player_id for e in entries])
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
                "trend": trends.get(e.player.espn_player_id),
                "consistency": consistency.get(e.player.espn_player_id),
                "fantasycalc": get_trade_value(league.fantasycalc_values, e.player.espn_player_id),
                "fp_injury": get_injury_context(league.fantasypros_injuries, e.player.espn_player_id),
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
    # Real FAAB balances and waiver order are premium; the endpoint stays
    # open so basic accounts keep their percentage-based bid hint.
    return get_waiver_targets(
        db, league.id, my_team_id, include_budget=has_premium_access(current_user)
    )


@app.get("/api/league/{league_id}/matchup-preview")
def matchup_preview(
    league_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_premium)
):
    """This week's head-to-head against your actual opponent. Premium."""
    league = _owned_league_or_404(db, league_id, current_user)
    my_team_id = _require_my_team(league)
    return get_matchup_preview(db, league.id, my_team_id)


@app.get("/api/league/{league_id}/matchup-live")
def matchup_live(
    league_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_premium)
):
    """Live scores for this week's matchup, read from ESPN on every call.

    Deliberately separate from /matchup-preview: that one is served from
    the database and is fast, this one goes out to ESPN twice and is not.
    Keeping them apart lets the tab render immediately and fill in the live
    numbers when they arrive. Premium.
    """
    league = _owned_league_or_404(db, league_id, current_user)
    my_team_id = _require_my_team(league)
    return get_live_matchup(db, league, my_team_id, current_user)


@app.get("/api/league/{league_id}/playoff-odds")
def playoff_odds(
    league_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_premium)
):
    """Rest-of-season simulation: playoff odds and remaining-schedule
    strength for every team. Premium."""
    league = _owned_league_or_404(db, league_id, current_user)
    my_team_id = _require_my_team(league)
    return get_playoff_odds(db, league.id, my_team_id)


@app.get("/api/league/{league_id}/activity")
def league_activity(
    league_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_premium)
):
    """Who's been claiming whom, what it cost, and how each manager spends.
    Premium. Populated at sync (see app/league_activity.py), so an empty
    feed means a re-sync is needed rather than that nothing happened."""
    league = _owned_league_or_404(db, league_id, current_user)
    activity = league.activity or {}
    return {
        "transactions": activity.get("transactions", []),
        "spending": activity.get("spending", []),
        "uses_faab": league.uses_faab,
        "acquisition_budget": league.acquisition_budget,
    }


@app.get("/api/league/{league_id}/trades")
def trades(league_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    league = _owned_league_or_404(db, league_id, current_user)
    my_team_id = _require_my_team(league)
    return get_trade_suggestions(db, league.id, my_team_id)


@app.get("/api/league/{league_id}/expert-rankings")
def expert_rankings(
    league_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    league = _owned_league_or_404(db, league_id, current_user)
    if not league.expert_rankings:
        return {"available": False}
    return {"available": True, **league.expert_rankings}


@app.get("/api/league/{league_id}/depth-charts")
def depth_charts(league_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    league = _owned_league_or_404(db, league_id, current_user)
    return {"depth_charts": compute_depth_charts(db, league.id)}


@app.get("/api/league/{league_id}/handcuffs")
def handcuffs(league_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    league = _owned_league_or_404(db, league_id, current_user)
    my_team_id = _require_my_team(league)
    return {"handcuffs": get_rb_handcuffs(db, league.id, my_team_id)}


@app.get("/api/league/{league_id}/changes")
def changes(league_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    league = _owned_league_or_404(db, league_id, current_user)
    if not league.sync_changes:
        return {"available": False, "synced_at": league.synced_at}
    return {"available": True, **league.sync_changes}


@app.get("/api/league/{league_id}/alerts")
def alerts(league_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    league = _owned_league_or_404(db, league_id, current_user)
    my_team_id = _require_my_team(league)
    return get_roster_alerts(db, league.id, my_team_id)


@app.get("/api/league/{league_id}/schedule-outlook")
def schedule_outlook(
    league_id: int,
    weeks: int = 4,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    league = _owned_league_or_404(db, league_id, current_user)
    my_team_id = _require_my_team(league)
    return get_schedule_outlook(db, league.id, my_team_id, weeks_ahead=max(1, min(weeks, 10)))


@app.get("/api/league/{league_id}/bench-points")
def bench_points(league_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    league = _owned_league_or_404(db, league_id, current_user)
    my_team_id = _require_my_team(league)
    try:
        return get_bench_points(db, league, my_team_id)
    except ESPNClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/league/{league_id}/teams-with-rosters")
def teams_with_rosters(
    league_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    league = _owned_league_or_404(db, league_id, current_user)
    teams = db.query(Team).filter(Team.league_id == league.id).order_by(Team.name).all()
    # One query for every team's roster (with players preloaded) instead of
    # a query per team plus one per player.
    entries = (
        db.query(RosterEntry)
        .filter(RosterEntry.team_id.in_([team.id for team in teams]))
        .options(selectinload(RosterEntry.player))
        .all()
    )
    entries_by_team = defaultdict(list)
    for entry in entries:
        entries_by_team[entry.team_id].append(entry)

    return [
        {
            "id": team.espn_team_id,
            "name": team.name,
            "roster": [
                {
                    "espn_player_id": e.player.espn_player_id,
                    "name": e.player.full_name,
                    "position": e.player.position,
                    "projected_points": e.player.projected_points,
                    # Lets the Trade Grader list players in the same lineup
                    # order as the Roster and Start/Sit tabs.
                    "slot": e.lineup_slot,
                    "is_starter": e.is_starter,
                }
                for e in entries_by_team.get(team.id, [])
            ],
        }
        for team in teams
    ]


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
