"""Instance-wide settings an admin can change from the Admin tab at
runtime, stored in the database (see models.AppSetting) rather than
backend/.env — no file edit or restart needed, and it works the same way
whether this instance was set up by hand or via install.sh.

Each setting here layers on top of (never replaces) its backend/.env
equivalent: the env var stays the zero-config path for a single-operator
install, this is for changing it afterward without shell access.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import settings
from app.models import AppSetting

FANTASYPROS_API_KEY = "fantasypros_api_key"


def get_fantasypros_api_key(db: Session) -> str | None:
    """The FantasyPros key actually in effect: a value saved from the
    Admin tab takes precedence over FANTASYPROS_API_KEY in backend/.env."""
    row = db.get(AppSetting, FANTASYPROS_API_KEY)
    if row and row.value:
        return row.value
    return settings.fantasypros_api_key


def fantasypros_api_key_source(db: Session) -> str | None:
    """Where the effective key (if any) comes from, for the Admin tab's
    status display — never the key itself. "database" also covers the
    edge case where the saved value happens to be empty/whitespace, which
    get_fantasypros_api_key() treats as unset."""
    row = db.get(AppSetting, FANTASYPROS_API_KEY)
    if row and row.value:
        return "database"
    if settings.fantasypros_api_key:
        return "config"
    return None


def set_fantasypros_api_key(db: Session, value: str | None) -> None:
    """Saves a new key, or clears the override (falling back to
    backend/.env, if anything) when value is empty/whitespace-only."""
    value = value.strip() if value else None
    row = db.get(AppSetting, FANTASYPROS_API_KEY)
    if value:
        if row:
            row.value = value
        else:
            db.add(AppSetting(key=FANTASYPROS_API_KEY, value=value))
    elif row:
        db.delete(row)
    db.commit()
