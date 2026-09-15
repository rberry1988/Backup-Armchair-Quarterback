import datetime

from pydantic import BaseModel, EmailStr, field_validator


class SyncRequest(BaseModel):
    league_id: int
    season: int


class SetMyTeamRequest(BaseModel):
    team_id: int


class TradeGradeRequest(BaseModel):
    team_a_id: int
    team_a_sends: list[int]
    team_b_id: int
    team_b_sends: list[int]


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


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
