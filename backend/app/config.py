from pydantic_settings import BaseSettings, SettingsConfigDict


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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
