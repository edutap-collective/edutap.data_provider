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
import os
from functools import lru_cache

import logfire
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
    record. Three are worth naming here, because each contradicts what the
    backend's own documentation recommends:

    `include_local_variables=False` -- with local variables on, the raw
    `Authorization` header sits in the ASGI scope, which is a local in most frames
    of an ASGI stack, and the bearer token appears dozens of times in an event whose
    rendered `authorization` header says `[Filtered]`. Sentry's scrubber matches key
    names; it does not walk a list of byte tuples.

    `max_request_body_size="never"` -- for this service the request body *is* the
    identifying datum, so there is no partial version of this.

    `max_breadcrumbs=0` -- Sentry's `LoggingIntegration` is on by default and turns
    every WARNING/ERROR `LogRecord` into a breadcrumb carrying the record's
    formatted `message` verbatim and unscrubbed, on a path none of the other four
    options constrains. Measured: `logger.warning("no view for person %s", uid)`
    puts the person's uid at `breadcrumbs.values[0].message` on the wire. Today
    this package logs exactly once, and that call names no value -- but the
    invariant this module exists to hold ("no credential and no personal datum
    leaves the process") has to survive the next line someone adds to it, not just
    the lines it has today. A `before_breadcrumb` hook that drops only
    `type == "log"` breadcrumbs was the narrower alternative, and was rejected:
    it would need re-auditing against every other breadcrumb-producing
    integration FastAPI or Sentry adds in the future, whereas turning breadcrumbs
    off closes the whole surface with one option, the same call this module
    already made for the request body. The cost is real: an event carries no
    timeline of what happened earlier in the request. For a stateless,
    single-route-per-request service that cost is small -- the exception, its
    (variable-free) traceback and the route are still on the event -- and it is
    the same trade this module made for local variables and the request body:
    less to read, nothing left to guess is safe.

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
        "max_breadcrumbs": 0,
    }


def scrub_request_attributes(request: object, attributes: dict) -> dict:
    """Replace a recorded request body, and its validation errors, with their shape.

    logfire's FastAPI instrumentation records two things as span attributes on every
    request: the validated endpoint arguments (`values`) and, on a rejected request,
    the raw Pydantic errors that rejected it (`errors`). For `/lookup` both can carry
    a `person_uid`, so neither raw mapping can be exported.

    The `errors` half exists because of a Pydantic detail, not a FastAPI one:
    measured directly, a "missing field" error's `input` is not the missing field's
    value -- it is the *whole enclosing dict*, because the error is reported against
    the model. A `/lookup` request missing `fields` but carrying a `person_uid`
    therefore has that `person_uid` sitting in `errors[0]["input"]` on a plain 422,
    with no exception anywhere in the picture.

    What survives is what makes a trace worth having -- which view was asked for and
    how many fields, or which field failed validation and how -- and not who was
    asked about. A body this function does not recognise is reduced to nothing
    rather than passed through: a later endpoint must not become an export path
    because no rule here happened to match it.
    """
    values = attributes.get("values")
    result = attributes
    if isinstance(values, dict) and "body" in values:
        body = values["body"]
        reduced = {
            "view_type": getattr(body, "view_type", None),
            "field_count": len(getattr(body, "fields", None) or []),
        }
        result = {**result, "values": {**values, "body": reduced}}

    errors = result.get("errors")
    if isinstance(errors, list):
        # `input` is the leak: on a Pydantic "missing" error it is the whole request
        # body, and on any other error type it is the value that failed. `type` and
        # `loc` are what is left -- which field, what kind of problem -- and they are
        # drawn from a small fixed vocabulary of Pydantic's own error type strings,
        # not from anything a caller supplied.
        result = {
            **result,
            "errors": [
                {"type": error.get("type"), "loc": error.get("loc")}
                for error in errors
                if isinstance(error, dict)
            ],
        }
    return result


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

    if settings.otlp_endpoint:
        # The exporter takes its endpoint from the OpenTelemetry environment, not
        # from an argument. Writing it here keeps the package's own configuration in
        # pydantic-settings, where every other value lives, instead of asking an
        # operator to set one variable in our namespace and one in OpenTelemetry's.
        # `setdefault`, not assignment: an operator who has set the OTel variable
        # deliberately -- alongside the protocol, header and timeout variables the
        # SDK also reads -- keeps their value.
        os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", settings.otlp_endpoint)
        logfire.configure(
            # No Pydantic cloud account and no token: this is logfire used as a
            # plain OTLP SDK against a self-hosted collector.
            send_to_logfire=False,
            service_name="edutap.data_provider",
            environment=settings.environment,
            console=False,
        )
