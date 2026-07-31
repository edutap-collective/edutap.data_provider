"""Configuration of the service process."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Everything the process needs to start."""

    model_config = SettingsConfigDict(
        env_prefix="EDUTAP_DATA_PROVIDER_",
        env_file=".env",
        extra="ignore",
    )

    # A DSN carries the database password in clear text and `BaseSettings.__repr__`
    # prints every plain field verbatim, so the URL is held as a secret just like the
    # token. Readers unwrap it with `get_secret_value()`.
    database_url: SecretStr
    config_path: Path
    api_token: SecretStr
    echo_sql: bool = False


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
