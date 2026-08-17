from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    app_env: str = "development"
    log_level: str = "INFO"

    tfgm_gtfs_url: str
    raw_data_dir: Path = Path("data/raw")
    processed_data_dir: Path = Path("data/processed")

    sql_server_host: str = "localhost"
    sql_server_port: int = 1433
    sql_server_database: str = "greater_manchester_transport"
    sql_server_username: str = "sa"
    sql_server_password: SecretStr = SecretStr("")
    sql_server_driver: str = "ODBC Driver 18 for SQL Server"
    sql_server_encrypt: bool = True
    sql_server_trust_certificate: bool = True

    serving_sqlite_path: Path = Path("data/serving/transport_dashboard.db")

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
