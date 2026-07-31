"""Configuration of the service process."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator
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

    @field_validator("api_token")
    @classmethod
    def _reject_an_empty_token(cls, value: SecretStr) -> SecretStr:
        """Refuse `EDUTAP_DATA_PROVIDER_API_TOKEN=` while the process is starting.

        An empty token authenticates nobody — `api.auth` refuses an empty credential
        outright — so such a deployment is a service that answers 401 to every call,
        forever, without a word. A required setting that is present but empty is a
        deployment mistake like a missing one, and belongs at the same place: load
        time, which `create_app` performs before the first request is accepted.

        A message of our own, not `Field(min_length=1)`: that renders as "Value
        should have at least 1 item after validation, not 0", which says nothing
        about a token to whoever has to fix it.
        """
        if not value.get_secret_value():
            raise ValueError(
                "must not be empty. A service with an empty token authenticates "
                "nobody and would answer 401 to every call."
            )
        return value


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
