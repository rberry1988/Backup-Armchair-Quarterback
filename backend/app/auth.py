from __future__ import annotations

import datetime
import time

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import JWT_SIGNING_KEY, settings
from app.db import get_db
from app.models import User

JWT_ALGORITHM = "HS256"
_bearer_scheme = HTTPBearer(auto_error=False)

# Failed-login throttling. Deliberately in-process and dependency-free:
# this is a single-box app, and the goal is only to make online password
# guessing impractical, not to be a distributed rate limiter. Note the
# deployed service runs two workers, so the effective ceiling is roughly
# double these numbers.
MAX_FAILED_ATTEMPTS = 8
ATTEMPT_WINDOW_SECONDS = 15 * 60
_failed_attempts: dict[tuple[str, str], list[float]] = {}


def _recent_failures(key: tuple[str, str], now: float) -> list[float]:
    attempts = [at for at in _failed_attempts.get(key, []) if now - at < ATTEMPT_WINDOW_SECONDS]
    if attempts:
        _failed_attempts[key] = attempts
    else:
        _failed_attempts.pop(key, None)
    return attempts


def _prune_attempts(now: float) -> None:
    """Keep the tracking dict from growing without bound as attackers cycle
    through addresses."""
    for key in list(_failed_attempts):
        _recent_failures(key, now)


def check_login_allowed(email: str, client_ip: str) -> None:
    """Raise 429 once this email/address pair has failed too many times."""
    now = time.monotonic()
    _prune_attempts(now)
    attempts = _recent_failures((email, client_ip), now)
    if len(attempts) >= MAX_FAILED_ATTEMPTS:
        retry_after = int(ATTEMPT_WINDOW_SECONDS - (now - min(attempts))) + 1
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed sign-in attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )


def record_failed_login(email: str, client_ip: str) -> None:
    _failed_attempts.setdefault((email, client_ip), []).append(time.monotonic())


def clear_failed_logins(email: str, client_ip: str) -> None:
    _failed_attempts.pop((email, client_ip), None)


def client_ip(request: Request) -> str:
    """The deployed nginx sets X-Real-IP from the socket peer, overwriting
    anything the client sent, and uvicorn only listens on localhost — so
    this header can't be spoofed in that setup. Falls back to the peer
    address when running the backend directly."""
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))


def create_access_token(user_id: int) -> str:
    expires_at = datetime.datetime.utcnow() + datetime.timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": str(user_id), "exp": expires_at}
    return jwt.encode(payload, JWT_SIGNING_KEY, algorithm=JWT_ALGORITHM)


def _decode_token(token: str) -> int:
    try:
        payload = jwt.decode(token, JWT_SIGNING_KEY, algorithms=[JWT_ALGORITHM])
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session") from exc


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    user_id = _decode_token(credentials.credentials)
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session")
    return user


def is_admin(user: User) -> bool:
    return user.email.lower() in settings.admin_email_list or user.admin_granted


def has_premium_access(user: User) -> bool:
    """Premium features (currently just the Extra tab) — granted directly
    via User.is_premium (an admin toggle, see main.py's admin_set_premium),
    or implied by admin access since admins already bypass every other
    gate in this app."""
    return is_admin(user) or user.is_premium


def is_admin_locked(user: User) -> bool:
    """True when admin status comes from ADMIN_EMAILS (backend/.env), not
    the database — those accounts can't be un-admin'd from the Admin tab,
    only by editing the config, so the UI shouldn't offer a toggle that
    would silently do nothing."""
    return user.email.lower() in settings.admin_email_list


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if not is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user
