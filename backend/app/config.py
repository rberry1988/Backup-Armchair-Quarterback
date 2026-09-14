from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    espn_league_id: int | None = None
    espn_season: int = 2025
    espn_s2: str | None = None
    espn_swid: str | None = None
    database_url: str = "sqlite:///./data/fantasy.db"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
