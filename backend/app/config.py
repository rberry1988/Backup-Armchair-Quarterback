import logging
import os
import secrets

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    espn_league_id: int | None = None
    espn_season: int = 2025
    espn_s2: str | None = None
    espn_swid: str | None = None
    database_url: str = "sqlite:///./data/fantasy.db"
    jwt_secret: str = "dev-secret-change-me"
    jwt_expire_minutes: int = 60 * 24 * 14  # 2 weeks
    # Comma-separated allowed origins for the browser CORS check. Only
    # matters for cross-origin setups (e.g. the Vite dev server on :5173
    # talking to the backend on :8000); a same-origin production
    # deployment behind a reverse proxy (see deploy/) never hits this.
    cors_origins: str = "http://localhost:5173"
    # Optional: enables the Expert Rankings tab and Trade Grader ECR
    # context (see app/fantasypros_client.py). Everything degrades to
    # "not available" without it — no key is required for the rest of
    # the app.
    fantasypros_api_key: str | None = None
    # Serves FastAPI's interactive docs at /docs and /redoc. Off by default:
    # this app is usually reachable by anyone on the LAN, and there's no
    # reason to publish the full API surface to them.
    enable_api_docs: bool = False
    # Comma-separated emails allowed to use the Admin tab (add/remove other
    # accounts). Deliberately config-driven rather than a DB column: an
    # admin flag stored in the database would need someone to already be an
    # admin to set it on the first account, which is a bootstrapping problem
    # this sidesteps entirely — you just list your own email here.
    admin_emails: str = ""
    # Lets an admin trigger a git pull + dependency/frontend rebuild +
    # restart from the Admin tab, instead of SSHing in to run install.sh
    # by hand. Off by default: it's meaningfully more powerful than
    # anything else behind the admin gate (it runs whatever code the next
    # commit contains), and only does anything useful when deploy/install.sh
    # actually deployed this instance as a git checkout it owns — see
    # app/deploy_service.py. install.sh turns this on itself.
    enable_self_update: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def admin_email_list(self) -> set[str]:
        return {email.strip().lower() for email in self.admin_emails.split(",") if email.strip()}


settings = Settings()

# Values that mean "nobody chose a secret" — the field default, and the
# placeholder .env.example ships. Signing sessions with any of them would
# let anyone who has read this repo forge a login for any user id.
PLACEHOLDER_JWT_SECRETS = {"dev-secret-change-me", "change-me-to-a-random-string", ""}

_SECRET_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "jwt_secret")


def _resolve_jwt_secret(configured: str) -> str:
    """The key sessions are actually signed with.

    Uses JWT_SECRET when it's really been set. Otherwise generates one and
    keeps it in backend/data/ so the app is never silently protected by a
    publicly-known string — and so sessions still survive a restart, which
    generating a fresh key each boot wouldn't do.
    """
    if configured.strip() not in PLACEHOLDER_JWT_SECRETS:
        return configured

    try:
        if os.path.exists(_SECRET_FILE):
            with open(_SECRET_FILE) as f:
                stored = f.read().strip()
            if stored:
                return stored

        generated = secrets.token_hex(32)
        os.makedirs(os.path.dirname(_SECRET_FILE), exist_ok=True)
        # Written 0600 — it's as sensitive as a password database.
        fd = os.open(_SECRET_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(generated)
        logger.warning(
            "JWT_SECRET is unset or still a placeholder. Generated one and stored it at "
            "backend/data/jwt_secret. Set JWT_SECRET in backend/.env to control it yourself."
        )
        return generated
    except OSError:
        # Read-only or otherwise unwritable data dir: a random per-process
        # key is still far better than a known one. Sessions won't survive
        # a restart, which the warning calls out.
        logger.warning(
            "JWT_SECRET is unset and backend/data/ is not writable — using a temporary key, so "
            "everyone will be logged out when this process restarts. Set JWT_SECRET in backend/.env."
        )
        return secrets.token_hex(32)


JWT_SIGNING_KEY = _resolve_jwt_secret(settings.jwt_secret)
