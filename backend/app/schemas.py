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


class AdminUserOut(BaseModel):
    id: int
    email: str
    created_at: datetime.datetime
    league_count: int
