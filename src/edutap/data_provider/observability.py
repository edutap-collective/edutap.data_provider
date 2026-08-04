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

    An *empty* salt counts as no salt, for the same reason an empty DSN counts as no
    DSN in `install_observability`: `compose.yml` writes `${VAR:-}`, which sets a
    variable to the empty string rather than leaving it unset. An HMAC under an
    empty key is a well-defined, entirely unkeyed digest -- precisely the reversible
    hash-the-directory construction the key exists to prevent, and indistinguishable
    from a real pseudonym by eye.
    """
    if salt is None or not salt.get_secret_value():
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


def _is_lookup_shaped(value: object) -> bool:
    """Whether `value` is a `LookupRequest`, regardless of its parameter name.

    Judged structurally rather than by name, because the name is not load-bearing:
    `/lookup`'s body parameter is called `request`, not `body` (`api/routers.py`),
    so a mapper that keys off the literal string `"body"` never fires against the
    real application -- measured directly against `create_app()`, where
    `fastapi.arguments.values` held the whole `config`, a `repository` object repr,
    and the person's uid under the key `request`, none of it touched. `view_type`
    and `fields` are the two attributes this module ever reads off the object, so
    they are also the two it checks for.
    """
    return hasattr(value, "view_type") and hasattr(value, "fields")


def scrub_request_attributes(request: object, attributes: dict) -> dict:
    """Replace every recorded endpoint argument, and validation error, with its shape.

    logfire's FastAPI instrumentation records two things as span attributes on every
    request: the validated endpoint arguments (`values`) and, on a rejected request,
    the raw Pydantic errors that rejected it (`errors`). For `/lookup` both can carry
    a `person_uid`, so neither raw mapping can be exported.

    `values` is keyed by parameter name, and parameter names are not a boundary
    this module controls -- a body parameter can be called `request`, `payload`,
    `lookup_request`, anything a future endpoint author chooses, and a query
    parameter could be named `person_uid` directly. So every entry is judged by
    what it *is*, not what it is called, and unrecognised is the default outcome,
    not passed-through:

    - a `LookupRequest`-shaped value (`_is_lookup_shaped`), under any key, reduces
      to `{"view_type": ..., "field_count": ...}` -- which view was asked for and
      how many fields, not who was asked about -- plus `"person"`, a keyed
      pseudonym of the same shape's `person_uid`, present only when a salt is
      configured, so a trace carries the same label an event does (see
      `routers.lookup`) rather than a second, differently-shaped way to identify
      someone;
    - the bare scalar under the key `"view_type"` survives unchanged, because
      `/catalogue` receives it directly as a query parameter rather than inside a
      body, and it is the one specific value this module knows is safe -- allow-
      listed by name for exactly this reason: unlike a `LookupRequest`, a bare
      string carries no structure to recognise it by, so nothing except this one
      known-safe name is let through as one;
    - anything else -- a FastAPI dependency such as `config` (the whole view
      configuration) or `repository`, a parameter this module has never seen, a
      bare scalar under any other name -- is dropped from the export entirely.

    The `errors` half exists because of a Pydantic detail, not a FastAPI one:
    measured directly, a "missing field" error's `input` is not the missing field's
    value -- it is the *whole enclosing dict*, because the error is reported against
    the model. A `/lookup` request missing `fields` but carrying a `person_uid`
    therefore has that `person_uid` sitting in `errors[0]["input"]` on a plain 422,
    with no exception anywhere in the picture. Every error entry is reduced the same
    way regardless of its position or the field it names: `type` and `loc` survive
    -- which field, what kind of problem, drawn from Pydantic's own fixed error-type
    vocabulary -- and `input` (and `msg`, which a future custom validator could put
    a value into) does not.
    """
    values = attributes.get("values")
    result = attributes
    if isinstance(values, dict):
        reduced_values: dict[str, object] = {}
        for key, value in values.items():
            if _is_lookup_shaped(value):
                reduced: dict[str, object] = {
                    "view_type": getattr(value, "view_type", None),
                    "field_count": len(getattr(value, "fields", None) or []),
                }
                person_uid = getattr(value, "person_uid", None)
                if person_uid is not None:
                    tag = pseudonym(person_uid, get_observability_settings().pseudonym_salt)
                    if tag is not None:
                        reduced["person"] = tag
                reduced_values[key] = reduced
            elif key == "view_type" and isinstance(value, str):
                reduced_values[key] = value
            # Anything else -- a dependency, an unrecognised parameter, a bare
            # scalar under any other name -- is simply not carried into
            # `reduced_values`, which is the "dropped rather than trusted" default.
        result = {**result, "values": reduced_values}

    errors = result.get("errors")
    if isinstance(errors, list):
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
        # Without a bound, an unreachable collector blocks shutdown -- interpreter
        # exit, and every SIGTERM -- for roughly the OpenTelemetry SDK's export
        # timeout *twice over*: once for whatever export the background batch
        # processor already had in flight, once more for the final
        # flush-everything-remaining call it issues as it shuts down. Measured
        # directly against this service, with one span emitted and a genuinely
        # unroutable collector address: 20.4s to exit, against the SDK's 10s
        # per-attempt default. That collides with an orchestrator's termination
        # grace period -- Docker's default is 10s -- and turns a graceful shutdown
        # into a SIGKILL, discarding whatever the process was doing mid-request.
        #
        # `OTEL_EXPORTER_OTLP_TIMEOUT` (seconds) is the lever actually wired to
        # this: confirmed by reading the installed exporter's source
        # (`opentelemetry-exporter-otlp-proto-http`), it bounds each export
        # attempt via `requests.Session.post(..., timeout=...)`. 3 seconds keeps
        # worst-case shutdown blocking near 6 seconds -- comfortably under
        # Docker's 10s grace period -- while staying generous next to a healthy
        # collector's response time, which is normally milliseconds; a slow but
        # working collector only loses a span if it cannot answer within 3s; a
        # value in the low single digits was chosen over something closer to 1s
        # specifically to leave that margin.
        os.environ.setdefault("OTEL_EXPORTER_OTLP_TIMEOUT", "3")
        # `OTEL_BSP_SCHEDULE_DELAY` (milliseconds): the interval between batch
        # flushes, shortened from the SDK's 5000ms default so a healthy collector
        # sees spans sooner and so less is ever queued -- and therefore blocking a
        # shutdown -- mid-flight when shutdown lands.
        os.environ.setdefault("OTEL_BSP_SCHEDULE_DELAY", "1000")
        # `OTEL_BSP_EXPORT_TIMEOUT` (milliseconds): read but, measured directly
        # against the installed opentelemetry-sdk (1.44), *not currently applied*
        # to the join() call shutdown makes on the batch processor's worker thread
        # -- the SDK's own source says so ("Not used. No way currently to pass
        # timeout to export.", tracked upstream as
        # open-telemetry/opentelemetry-python#4555). Set anyway, matched to the
        # value above, so a future SDK release that does wire it up inherits a
        # value already chosen for this service rather than the 30s default.
        os.environ.setdefault("OTEL_BSP_EXPORT_TIMEOUT", "3000")
        logfire.configure(
            # No Pydantic cloud account and no token: this is logfire used as a
            # plain OTLP SDK against a self-hosted collector.
            send_to_logfire=False,
            service_name="edutap.data_provider",
            environment=settings.environment,
            console=False,
        )
