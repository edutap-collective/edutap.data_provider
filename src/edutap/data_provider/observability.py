"""Error reporting and tracing, and the boundary of what may leave the process.

The service exists to keep pass-issuing consumers from seeing more personal data
than they need. An error tracker is a machine that copies the state around a
failure to a second system, which is the one thing the service is built not to do,
so every option here was chosen against a measurement of what actually reaches the
wire rather than from a backend's recommendation. The measurements are recorded in
`docs/superpowers/specs/2026-08-04-observability-design.md`.
"""

import hashlib
import hmac
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def pseudonym(person_uid: str, salt: SecretStr | None) -> str | None:
    """Return a keyed, truncated stand-in for a person, or nothing without a key.

    Keyed rather than a plain digest: a `person_uid` comes from a directory, so the
    value space is small and enumerable and an unsalted hash would be reversible by
    anyone able to read the error tracker — simply by hashing the directory.

    Truncated to 12 hex characters, 48 bits: wide enough that two people in one
    installation colliding is not a practical concern, short enough that the result
    reads as a label rather than as an identifier worth storing.
    """
    if salt is None:
        return None
    digest = hmac.new(
        salt.get_secret_value().encode("utf-8"),
        person_uid.encode("utf-8"),
        hashlib.sha256,
    )
    return digest.hexdigest()[:12]


class ObservabilitySettings(BaseSettings):
    """Where to report, and under what name. Every field optional.

    Deliberately not part of `Settings`. `create_app` installs observability
    *before* it resolves the settings the service needs to run, so that a process
    refusing to start is reported rather than silently absent. That ordering is only
    possible if reading these can never fail — which is why nothing here is
    required, and why this model lives beside the module that uses it rather than in
    `settings.py`.
    """

    model_config = SettingsConfigDict(
        env_prefix="EDUTAP_DATA_PROVIDER_",
        env_file=".env",
        extra="ignore",
    )

    # A DSN is a credential, and `BaseSettings.__repr__` prints every plain field
    # verbatim — the same reason `Settings.database_url` is a secret.
    sentry_dsn: SecretStr | None = None
    otlp_endpoint: str | None = None
    # The HMAC key behind the person pseudonym. Without it there is no pseudonym at
    # all, rather than one computed from an empty key.
    pseudonym_salt: SecretStr | None = None
    environment: str = "production"


@lru_cache
def get_observability_settings() -> ObservabilitySettings:
    """Return the process-wide observability settings."""
    return ObservabilitySettings()
