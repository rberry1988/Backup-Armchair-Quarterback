import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator


def _min_length_password(v: str) -> str:
    if len(v) < 8:
        raise ValueError("Password must be at least 8 characters")
    return v


class SyncRequest(BaseModel):
    league_id: int
    season: int


class SetMyTeamRequest(BaseModel):
    team_id: int


class TradeGradeRequest(BaseModel):
    team_a_id: int
    # Capped well above any real roster size (typically ~16-20 players) —
    # mainly to keep grade_trade()'s per-player DB lookups bounded rather
    # than letting a malformed/adversarial request force an arbitrarily
    # large batch query.
    team_a_sends: list[int] = Field(max_length=25)
    team_b_id: int
    team_b_sends: list[int] = Field(max_length=25)


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str

    _validate_password = field_validator("password")(_min_length_password)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    _validate_password = field_validator("new_password")(_min_length_password)


class ResetPasswordRequest(BaseModel):
    """Admin-only: set someone's password without knowing their current one."""

    new_password: str

    _validate_password = field_validator("new_password")(_min_length_password)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    email: str
    is_admin: bool = False
    # Effective premium access (own grant OR admin) — see auth.has_premium_access.
    is_premium: bool = False
    display_name: str | None = None


class UpdateDisplayNameRequest(BaseModel):
    # Empty/whitespace clears it, falling back to the account's email
    # everywhere it's shown.
    display_name: str = Field(max_length=50)

    @field_validator("display_name")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class EspnCredentialsRequest(BaseModel):
    """A user's own ESPN session cookies. Sending either one empty clears
    both — a half-set session isn't usable, and "disconnect" should be one
    action rather than two."""

    # Generous bounds: espn_s2 is a long opaque blob (~300+ chars and it has
    # grown before), SWID is a brace-wrapped UUID.
    espn_s2: str = Field(default="", max_length=2000)
    swid: str = Field(default="", max_length=100)


class EspnCredentialsStatus(BaseModel):
    """Deliberately says only *whether* cookies are saved. They're bearer
    credentials to someone's whole ESPN account, so they are never sent
    back out — not even to the person who saved them."""

    connected: bool


class WebhookRequest(BaseModel):
    """Empty/whitespace clears it and turns notifications off."""

    # Bounded here as well as in notifications.webhook_url_error, so an
    # oversized body is rejected before any of it is parsed as a URL.
    webhook_url: str = Field(default="", max_length=400)


class WebhookStatus(BaseModel):
    configured: bool
    # The service the saved URL points at ("Discord"/"Slack"), never the
    # URL itself — it's a bearer token for posting into someone's channel.
    service: str | None = None


class AdminUserOut(BaseModel):
    id: int
    email: str
    created_at: datetime.datetime
    league_count: int
    is_admin: bool = False
    # True when admin status comes from ADMIN_EMAILS in backend/.env rather
    # than a grant made from this tab — the UI shows those as a fixed badge
    # instead of a toggle, since flipping the DB flag wouldn't change
    # anything (see auth.is_admin/is_admin_locked).
    admin_locked: bool = False
    # Raw premium grant (not OR'd with admin status) — the Admin tab's
    # toggle controls exactly this flag.
    is_premium: bool = False


class SetAdminRequest(BaseModel):
    is_admin: bool


class SetPremiumRequest(BaseModel):
    is_premium: bool


class PlannedMoveRequest(BaseModel):
    add_espn_player_id: int
    add_name: str = Field(max_length=100)
    add_position: str = Field(default="", max_length=10)
    drop_espn_player_id: int | None = None
    drop_name: str | None = Field(default=None, max_length=100)
    # % of a standard 100-point FAAB budget.
    faab_bid: int | None = Field(default=None, ge=0, le=100)
    note: str | None = Field(default=None, max_length=200)


class AutoSyncRequest(BaseModel):
    enabled: bool
    # Bounds match app/auto_sync.py's clamp; anything outside is a client
    # bug rather than something to silently round into range.
    interval_hours: int = Field(default=12, ge=1, le=168)


class FantasyProsKeyRequest(BaseModel):
    # Empty/whitespace clears a previously-saved key, falling back to
    # FANTASYPROS_API_KEY in backend/.env (if set).
    api_key: str


class FantasyProsKeyStatus(BaseModel):
    configured: bool
    # "database" (saved from this tab), "config" (backend/.env), or None.
    source: str | None = None
