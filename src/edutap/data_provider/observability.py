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
import logging
from functools import lru_cache

import sentry_sdk
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sentry_sdk.utils import BadDsn


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


def sentry_options(settings: ObservabilitySettings) -> dict[str, object]:
    """Return the options that decide what leaves the process.

    Each was chosen against a measurement, and the measurements are in the design
    record. Two are worth naming here, because both contradict what the backend's
    own documentation recommends:

    `include_local_variables=False` -- with local variables on, the raw
    `Authorization` header sits in the ASGI scope, which is a local in most frames
    of an ASGI stack, and the bearer token appears dozens of times in an event whose
    rendered `authorization` header says `[Filtered]`. Sentry's scrubber matches key
    names; it does not walk a list of byte tuples.

    `max_request_body_size="never"` -- for this service the request body *is* the
    identifying datum, so there is no partial version of this.

    Returned as a mapping rather than applied inline so a test can configure a fake
    transport with exactly these options, and cannot pass by being stricter than the
    service.
    """
    return {
        "environment": settings.environment,
        # Bugsink states that it "intentionally does not support traces". Traces go
        # to the OTLP collector instead; nothing travels both paths.
        "traces_sample_rate": 0,
        "send_default_pii": False,
        "include_local_variables": False,
        "max_request_body_size": "never",
    }


def install_observability(settings: ObservabilitySettings) -> None:
    """Configure error reporting and tracing, or configure nothing at all.

    Never raises. An error tracker that stops the service from starting has inverted
    its own purpose, so a misconfigured backend must cost telemetry and nothing else.

    The guard is narrow, and it is not speculative. Measured: an *unreachable* DSN
    initialises fine and fails later in the background, while a *malformed* one --
    `sentry_sdk.init("bugsink.example/1")`, a missing public key, one typo in a
    deployment variable -- raises `BadDsn` from `init` itself and would take the
    whole service down with it. logfire was measured under the analogous
    misconfiguration, an unparseable endpoint, and does not raise from `configure`,
    so it gets no guard it does not need.
    """
    dsn = settings.sentry_dsn.get_secret_value() if settings.sentry_dsn else ""
    if dsn:
        try:
            # `sentry_options` returns `dict[str, object]` so it can be reused as a
            # fixed mapping in tests; spreading it against `sentry_sdk.init`'s many
            # narrowly typed keyword parameters is exactly what a plain dict cannot
            # express to a type checker, hence the ignore rather than a change to
            # what the dict actually carries.
            sentry_sdk.init(
                dsn=dsn,
                **sentry_options(settings),  # ty: ignore[invalid-argument-type]
            )
        except BadDsn:
            # `logging`, not `raise`: the service must come up. The DSN is a
            # credential, so the message names the variable to go and fix and never
            # the value that is wrong with it.
            logging.getLogger(__name__).error(
                "EDUTAP_DATA_PROVIDER_SENTRY_DSN is not a valid DSN; "
                "error reporting is disabled for this process."
            )
