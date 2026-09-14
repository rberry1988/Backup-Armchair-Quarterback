from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    espn_league_id: int | None = None
    espn_season: int = 2025
    espn_s2: str | None = None
    espn_swid: str | None = None
    database_url: str = "sqlite:///./data/fantasy.db"
    jwt_secret: str = "dev-secret-change-me"
    jwt_expire_minutes: int = 60 * 24 * 14  # 2 weeks

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
