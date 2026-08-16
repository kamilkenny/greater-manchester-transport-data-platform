from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    app_env: str = "development"
    log_level: str = "INFO"

    tfgm_gtfs_url: str
    raw_data_dir: Path = Path("data/raw")
    processed_data_dir: Path = Path("data/processed")

    azure_sql_server: str = ""
    azure_sql_database: str = ""
    azure_sql_username: str = ""
    azure_sql_password: str = ""
    azure_sql_driver: str = "ODBC Driver 18 for SQL Server"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return one cached settings instance for the application."""

    return Settings()
