"""What may leave the process, pinned."""

import json
import os

import logfire
import pytest
import sentry_sdk
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import BaseModel, SecretStr

from edutap.data_provider.observability import ObservabilitySettings, pseudonym, sentry_options

SALT = SecretStr("a-salt")
OTHER_SALT = SecretStr("another-salt")

TOKEN = "super-secret-token"  # noqa: S105  a probe value, not a credential
PERSON_UID = "u123456"
CLIENT_IP = "10.1.2.3"


def test_the_pseudonym_is_stable_for_one_person_and_salt():
    assert pseudonym("u123456", SALT) == pseudonym("u123456", SALT)


def test_different_people_get_different_pseudonyms():
    assert pseudonym("u123456", SALT) != pseudonym("u654321", SALT)


def test_rotating_the_salt_renames_everybody():
    """The intended property: a pseudonym does not follow a person across a rotation."""
    assert pseudonym("u123456", SALT) != pseudonym("u123456", OTHER_SALT)


def test_without_a_salt_there_is_no_pseudonym():
    """Not a pseudonym computed from an empty key. Enabling this is deliberate."""
    assert pseudonym("u123456", None) is None


def test_the_pseudonym_never_contains_the_person_uid():
    person_uid = "u123456"

    result = pseudonym(person_uid, SALT)

    assert person_uid not in result


@pytest.mark.parametrize("person_uid", ["u123456", "", "Grüße-mit-Umlaut", "a" * 500])
def test_the_pseudonym_is_twelve_hex_characters(person_uid):
    """A label, not a stored identifier. Non-ASCII must not raise."""
    result = pseudonym(person_uid, SALT)

    assert len(result) == 12
    assert all(character in "0123456789abcdef" for character in result)


def test_the_salt_is_the_hmac_key_not_the_person_uid():
    """Pins the argument order Task 2's review parked as unchecked.

    `hmac.new(key, msg, digestmod)` is not commutative in general, so a reversed
    call -- the person as the key, the salt as the message -- computes a different
    digest and would otherwise pass every test above it: they only ever compare two
    `pseudonym(...)` results against each other, never against an independently
    computed value, so a swap inside the function would go unnoticed. This test
    reproduces `pseudonym`'s digest by hand, with the order the docstring claims
    ("Keyed rather than a plain digest"), and fails if the implementation swaps it.
    """
    import hashlib as _hashlib
    import hmac as _hmac

    person_uid = "u123456"

    expected = _hmac.new(
        SALT.get_secret_value().encode("utf-8"),
        person_uid.encode("utf-8"),
        _hashlib.sha256,
    ).hexdigest()[:12]

    assert pseudonym(person_uid, SALT) == expected


@pytest.fixture
def sentry_events():
    """Capture what Sentry would send, using the production options verbatim.

    The transport is the only thing replaced. Everything that decides *content*
    comes from `sentry_options`, so this test cannot pass because the test
    configured Sentry more strictly than the service does.
    """
    captured: list[dict] = []

    class Capture(sentry_sdk.transport.Transport):
        def capture_envelope(self, envelope):
            for item in envelope.items:
                captured.append(item.payload.json)

    sentry_sdk.init(
        dsn="https://public@example.invalid/1",
        transport=Capture(),
        **sentry_options(ObservabilitySettings()),
    )
    yield captured
    # Leave no client behind: `sentry_sdk.init` is process-global, and a later test
    # raising an exception would otherwise still be reporting into this list.
    #
    # Measured: `sentry_sdk.init(dsn=None)` does not achieve this under sentry-sdk
    # 2.66 -- `_Client.is_active()` returns `True` unconditionally once a real
    # `_Client` exists, whether or not it has a dsn, so a later no-dsn test would see
    # a contaminated, "active" global client. Clearing the global scope's client
    # directly restores the `NonRecordingClient` placeholder that `is_active()`
    # correctly reports as inactive.
    sentry_sdk.get_global_scope().set_client(None)


def _probe_app() -> FastAPI:
    """An application shaped like the real one where it matters: a body carrying a
    person, and a handler that fails after the body has been read."""
    import logging

    app = FastAPI()
    logger = logging.getLogger("edutap.data_provider.probe")

    class Lookup(BaseModel):
        person_uid: str
        view_type: str
        fields: list[str]

    @app.post("/lookup")
    async def lookup(body: Lookup) -> dict:
        # Shaped after the regression this probe exists to catch: an ordinary
        # WARNING log call, naming the person it is about, written the way anyone
        # adding diagnostics to a route would write it -- with no reason to know
        # that Sentry's LoggingIntegration turns WARNING/ERROR log records into
        # breadcrumbs that ship the formatted message verbatim, unscrubbed, on a
        # path none of the five options constrains.
        logger.warning("no view configured for person %s", body.person_uid)
        raise RuntimeError("the stored data for this person is unusable")

    return app


def test_no_credential_and_no_person_reaches_the_error_tracker(sentry_events):
    """The test this whole design exists for.

    Asserted against the serialised event as a whole rather than against named
    fields, because the leak that motivated this was in
    `exception.values[0].stacktrace.frames[*].vars.scope.headers` -- a place no
    reasonable list of fields to check would have named. The bearer token appeared
    there 25 times while the `authorization` header itself rendered as `[Filtered]`.
    """
    client = TestClient(_probe_app(), raise_server_exceptions=False)

    client.post(
        "/lookup",
        headers={"Authorization": f"Bearer {TOKEN}", "X-Real-Ip": CLIENT_IP},
        json={"person_uid": PERSON_UID, "view_type": "mensapass", "fields": ["display_name"]},
    )

    assert sentry_events, "no event captured -- the probe proves nothing"
    blob = json.dumps(sentry_events)
    assert TOKEN not in blob
    assert PERSON_UID not in blob
    assert CLIENT_IP not in blob


def test_the_error_still_arrives(sentry_events):
    """The counterpart. A tracker that reports nothing also leaks nothing."""
    client = TestClient(_probe_app(), raise_server_exceptions=False)

    client.post(
        "/lookup",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"person_uid": PERSON_UID, "view_type": "mensapass", "fields": ["display_name"]},
    )

    types = [
        value["type"]
        for event in sentry_events
        for value in event.get("exception", {}).get("values", [])
    ]
    assert "RuntimeError" in types


def test_traces_are_off_because_bugsink_discards_them():
    """Not a sampling preference: Bugsink documents that it does not accept traces."""
    assert sentry_options(ObservabilitySettings())["traces_sample_rate"] == 0


def test_the_environment_cleared_between_tests_covers_the_whole_otel_namespace():
    """`conftest.py`'s autouse fixture must clear every `OTEL_*` variable, not one
    name it happens to know about.

    A first version cleared only `OTEL_EXPORTER_OTLP_ENDPOINT`. Review found
    `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` builds an identical network exporter and
    was left ambient (measured: 14.55s across three tests with only that sibling
    variable set) -- `_METRICS_ENDPOINT` and `_LOGS_ENDPOINT` follow by the same
    construction, and the OpenTelemetry specification defines more variables than
    any one list here could enumerate and keep current. Testing the *rule*
    (prefix, not name) directly, rather than the fixture's effect on this one
    process's environment at this one moment -- which by the time this test body
    runs has already had the fixture's own setup applied, and so could never by
    itself prove what an *ambient*, pre-existing shell variable would see.
    """
    import conftest

    environ = {
        "OTEL_EXPORTER_OTLP_ENDPOINT": "x",
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "x",
        "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT": "x",
        "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "x",
        "OTEL_A_FUTURE_SDK_VERSION_ADDS_THIS_ONE": "x",
        "EDUTAP_DATA_PROVIDER_SENTRY_DSN": "x",
        "UNRELATED_VARIABLE_MUST_SURVIVE": "x",
    }

    cleared = conftest._keys_to_clear(environ)

    assert set(cleared) == {
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
        "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
        "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT",
        "OTEL_A_FUTURE_SDK_VERSION_ADDS_THIS_ONE",
        "EDUTAP_DATA_PROVIDER_SENTRY_DSN",
    }


def test_nothing_is_installed_without_a_dsn():
    """Every other test in the suite runs in this state."""
    from edutap.data_provider.observability import install_observability

    install_observability(ObservabilitySettings())

    assert not sentry_sdk.get_client().is_active()


def test_a_malformed_dsn_does_not_stop_the_service(caplog):
    """One typo in a deployment variable must not take the service down.

    Measured before writing this: an unreachable DSN initialises fine, but a
    malformed one raises `BadDsn` out of `sentry_sdk.init` itself. An error tracker
    that prevents the service from starting has inverted its own purpose.
    """
    from edutap.data_provider.observability import install_observability

    install_observability(ObservabilitySettings(sentry_dsn=SecretStr("bugsink.example/1")))

    assert not sentry_sdk.get_client().is_active()
    assert "EDUTAP_DATA_PROVIDER_SENTRY_DSN" in caplog.text
    assert "bugsink.example" not in caplog.text, "the log names the variable, not the value"


def test_an_empty_dsn_does_not_count_as_configured():
    """compose.yml writes `${VAR:-}`, which sets the variable to the empty string
    rather than leaving it unset. An empty DSN must mean off, not a broken client."""
    from edutap.data_provider.observability import install_observability

    install_observability(ObservabilitySettings(sentry_dsn=SecretStr("")))

    assert not sentry_sdk.get_client().is_active()


def test_an_unexpected_500_of_the_real_app_reaches_the_error_tracker(
    sentry_events, configured_environment, monkeypatch
):
    """The blanket `Exception` handler must not swallow the report.

    `install_error_handlers` registers a handler for `Exception` so that an
    unexpected failure renders as problem+json instead of text/plain. If that
    handler ended the exception's journey, every unexpected 500 would be invisible
    in Bugsink -- and an opaque 500 that nobody is told about is worse than no
    handler at all.
    """
    from edutap.data_provider.api import routers
    from edutap.data_provider.api.app import create_app

    app = create_app()

    # `catalogue_for` is called without `await` in `routers.catalogue`, so the
    # replacement must be synchronous too -- an `async def` here would return an
    # unawaited coroutine instead of raising, and the route would fail FastAPI's
    # response validation rather than exercise the blanket `Exception` handler.
    def explode(*args, **kwargs):
        raise RuntimeError("something no handler expected")

    monkeypatch.setattr(routers, "catalogue_for", explode)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get(
        "/catalogue",
        params={"view_type": "mensapass"},
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 500
    types = [
        value["type"]
        for event in sentry_events
        for value in event.get("exception", {}).get("values", [])
    ]
    assert "RuntimeError" in types, "the blanket handler swallowed the report"


def test_nothing_is_instrumented_without_an_otlp_endpoint(monkeypatch):
    """The counterpart to `test_nothing_is_installed_without_a_dsn`, for logfire.
    Every other test in this file that does not set an OTLP endpoint runs in this
    state -- and until now, nothing pinned it.
    """
    calls: list[dict] = []
    monkeypatch.setattr(logfire, "configure", lambda **kwargs: calls.append(kwargs))
    from edutap.data_provider.observability import install_observability

    install_observability(ObservabilitySettings())

    assert calls == []


def test_the_otlp_endpoint_configures_logfire_against_the_opentelemetry_environment(
    monkeypatch,
):
    """The exporter reads its endpoint from the OpenTelemetry SDK's own environment
    variable, not from an argument to `logfire.configure` -- so both halves of
    `install_observability`'s OTLP block are pinned here: the environment variable
    it writes, and the fixed, non-cloud options it always passes.
    """
    calls: list[dict] = []
    monkeypatch.setattr(logfire, "configure", lambda **kwargs: calls.append(kwargs))
    from edutap.data_provider.observability import install_observability

    install_observability(ObservabilitySettings(otlp_endpoint="http://collector.example:4318"))

    assert os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://collector.example:4318"
    assert calls == [
        {
            "send_to_logfire": False,
            "service_name": "edutap.data_provider",
            "environment": "production",
            "console": False,
        }
    ]


def test_the_otlp_block_bounds_the_export_and_batch_timeouts(monkeypatch):
    """Without a bound, an unreachable collector blocks shutdown -- interpreter
    exit, and every SIGTERM -- for roughly the OpenTelemetry SDK's export timeout
    *twice over* (once for whatever export was already in flight, once for the
    final flush-everything-remaining call the batch processor issues on
    shutdown). Measured directly: 20.4s to exit a process that had emitted one
    span, against the SDK's 10s-per-attempt default -- long enough to collide
    with an orchestrator's termination grace period (Docker's default is 10s)
    and turn a graceful shutdown into a SIGKILL. See
    `test_shutdown_against_an_unreachable_collector_is_bounded` for the real,
    timed reproduction; this test only pins the three values that fix it.
    """
    calls: list[dict] = []
    monkeypatch.setattr(logfire, "configure", lambda **kwargs: calls.append(kwargs))
    from edutap.data_provider.observability import install_observability

    install_observability(ObservabilitySettings(otlp_endpoint="http://collector.example:4318"))

    assert os.environ["OTEL_EXPORTER_OTLP_TIMEOUT"] == "3"
    assert os.environ["OTEL_BSP_SCHEDULE_DELAY"] == "1000"
    assert os.environ["OTEL_BSP_EXPORT_TIMEOUT"] == "3000"


def test_an_operators_shutdown_timeout_choices_are_not_overridden(monkeypatch):
    """The mirror of `test_an_operators_otel_endpoint_choice_is_not_overridden`,
    for the three timeout/interval variables the fix above adds."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TIMEOUT", "7")
    monkeypatch.setenv("OTEL_BSP_SCHEDULE_DELAY", "2500")
    monkeypatch.setenv("OTEL_BSP_EXPORT_TIMEOUT", "9000")
    monkeypatch.setattr(logfire, "configure", lambda **kwargs: None)
    from edutap.data_provider.observability import install_observability

    install_observability(ObservabilitySettings(otlp_endpoint="http://collector.example:4318"))

    assert os.environ["OTEL_EXPORTER_OTLP_TIMEOUT"] == "7"
    assert os.environ["OTEL_BSP_SCHEDULE_DELAY"] == "2500"
    assert os.environ["OTEL_BSP_EXPORT_TIMEOUT"] == "9000"


@pytest.mark.slow
def test_shutdown_against_an_unreachable_collector_is_bounded():
    """The measured defect this round closes, timed for real.

    Chose a self-contained TCP listener over an external "black hole" address
    (an unroutable RFC1918 address, or a reserved documentation range like
    192.0.2.0/24) specifically because this test has to run on a CI runner whose
    outbound network policy this suite does not control: a private address's
    black-holing behaviour depends on the runner's own network layout, and even a
    range that is never announced on the public internet depends on the runner
    having ordinary internet egress at all, which is not guaranteed. Binding to
    `127.0.0.1` and never calling `accept()` depends on nothing external: the
    kernel completes the TCP handshake for a connection sitting in the listen
    backlog, so the exporter's *connect* succeeds immediately and only the
    *response* never arrives -- reliably reproducing a hang bounded by
    `OTEL_EXPORTER_OTLP_TIMEOUT`'s read-timeout, on loopback, on any machine that
    can open a socket to itself.

    Measured, both directions, with this exact reproduction: unfixed, ~10.44s
    (matching the OpenTelemetry SDK's 10s default almost exactly -- a read
    timeout raises `requests.exceptions.ReadTimeout`, which is not a
    `ConnectionError`, so the exporter's internal single retry-on-`ConnectionError`
    does not trigger here, unlike the roughly-doubled ~20s seen against a
    connection that is refused or black-holed outright). Fixed, ~3.4s, matching
    the 3-second `OTEL_EXPORTER_OTLP_TIMEOUT` this round sets, one attempt, no
    retry. The bound below sits between the two, with margin on both sides for
    scheduling noise on a loaded CI runner.
    """
    import socket
    import subprocess
    import sys
    import time

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    listener.listen(1)
    # Deliberately never `accept()`ed, never closed until the test ends: the
    # subprocess below connects into the backlog and then waits forever for a
    # response this process never sends.

    code = (
        "import sys; sys.path.insert(0, 'src')\n"
        "from edutap.data_provider.observability import ObservabilitySettings\n"
        "from edutap.data_provider.observability import install_observability\n"
        f"install_observability(ObservabilitySettings(otlp_endpoint='http://127.0.0.1:{port}'))\n"
        "import logfire\n"
        "with logfire.span('probe'):\n"
        "    pass\n"
    )

    try:
        start = time.monotonic()
        # `sys.executable` and `code` are both hardcoded above, not untrusted
        # input -- this runs the same interpreter running the test suite, on a
        # literal string.
        subprocess.run(  # noqa: S603  fixed interpreter, fixed literal script, no untrusted input
            [sys.executable, "-c", code], capture_output=True, text=True, timeout=30
        )
        elapsed = time.monotonic() - start
    finally:
        listener.close()

    assert elapsed < 7, (
        f"shutdown took {elapsed:.1f}s -- must stay well clear of the "
        "unfixed ~10.4s and of a 10s SIGTERM grace period"
    )


def test_an_operators_otel_endpoint_choice_is_not_overridden(monkeypatch):
    """`os.environ.setdefault`, not assignment: an operator who has set the
    OpenTelemetry variable directly -- alongside the protocol, header and timeout
    variables the SDK also reads -- keeps their own value.
    """
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://operator-chosen.example:4318")
    monkeypatch.setattr(logfire, "configure", lambda **kwargs: None)
    from edutap.data_provider.observability import install_observability

    install_observability(ObservabilitySettings(otlp_endpoint="http://our-default.example:4318"))

    assert os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://operator-chosen.example:4318"


def test_configuring_sentry_does_not_configure_logfire(monkeypatch):
    """The two backends are gated on their own setting; configuring one must not
    configure, or disable, the other.

    `sentry_sdk.init` is mocked too, not just `logfire.configure`: a real call
    leaves an "active" global client behind regardless of teardown within this
    one test (the same sentry-sdk 2.66 property the `sentry_events` fixture's own
    comment documents), which would otherwise contaminate whichever test happens
    to run next. This test only needs to know Sentry's own init was *attempted*
    with a real dsn, not to actually configure the global SDK state.
    """
    logfire_calls: list[dict] = []
    monkeypatch.setattr(logfire, "configure", lambda **kwargs: logfire_calls.append(kwargs))
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: None)
    from edutap.data_provider.observability import install_observability

    install_observability(
        ObservabilitySettings(sentry_dsn=SecretStr("https://public@example.invalid/1"))
    )

    assert logfire_calls == []


def test_configuring_logfire_does_not_configure_sentry(monkeypatch):
    """The mirror image of the test above."""
    monkeypatch.setattr(logfire, "configure", lambda **kwargs: None)
    from edutap.data_provider.observability import install_observability

    install_observability(ObservabilitySettings(otlp_endpoint="http://collector.example:4318"))

    assert not sentry_sdk.get_client().is_active()


def test_install_observability_never_raises_for_an_unparseable_otlp_endpoint():
    """Measured directly (see `install_observability`'s own docstring): unlike
    Sentry's `BadDsn`, logfire does not raise from `configure` under a malformed
    endpoint, so this half gets no guard -- but nothing pinned that measurement
    until now. Run for real, not mocked, matching how
    `test_a_malformed_dsn_does_not_stop_the_service` exercises the Sentry side:
    confirmed separately (not asserted here, to keep this test fast and
    deterministic) that this returns in well under a second, repeatably.
    """
    from edutap.data_provider.observability import install_observability

    install_observability(ObservabilitySettings(otlp_endpoint="not a url at all"))
    # No exception is the assertion.


def test_the_recorded_arguments_keep_the_shape_and_drop_the_person():
    """logfire records endpoint arguments on every *successful* request.

    Measured before this mapper existed: the span attribute
    `fastapi.arguments.values` held
    `{"body":{"person_uid":"u123456","view_type":"mensapass",...}}` on a plain 200.
    That is worse than the Sentry case, which only sends on an error.
    """
    from edutap.data_provider.observability import scrub_request_attributes

    class Lookup(BaseModel):
        person_uid: str
        view_type: str
        fields: list[str]

    body = Lookup(person_uid=PERSON_UID, view_type="mensapass", fields=["display_name", "uid"])

    result = scrub_request_attributes(None, {"values": {"body": body}})

    assert PERSON_UID not in json.dumps(result, default=str)
    assert result["values"]["body"] == {"view_type": "mensapass", "field_count": 2}


@pytest.mark.parametrize("parameter_name", ["body", "request", "payload", "lookup_request"])
def test_a_lookup_shaped_value_is_recognised_under_any_parameter_name(parameter_name):
    """The Critical review finding: `/lookup`'s body parameter is called `request`,
    not `body` (`api/routers.py`), so a mapper that only ever checked for the
    literal key `"body"` never fired against the real application. Recognition has
    to be by shape -- `view_type` and `fields` present -- not by what a parameter
    happens to be named, present or future.
    """
    from edutap.data_provider.observability import scrub_request_attributes

    class Lookup(BaseModel):
        person_uid: str
        view_type: str
        fields: list[str]

    body = Lookup(person_uid=PERSON_UID, view_type="mensapass", fields=["display_name"])

    result = scrub_request_attributes(None, {"values": {parameter_name: body}})

    assert PERSON_UID not in json.dumps(result, default=str)
    assert result["values"][parameter_name] == {"view_type": "mensapass", "field_count": 1}


@pytest.mark.parametrize("parameter_name", ["config", "repository"])
def test_a_dependency_injected_object_is_dropped_not_exported(parameter_name):
    """`config` (the whole view configuration) and `repository` are FastAPI
    dependencies, not user input, and carry nothing a trace wants. Measured
    against the real app: both appeared verbatim in `fastapi.arguments.values`
    before this fix, `config` as the entire view configuration and `repository`
    as an object repr. Neither matches the one recognised shape, so both must be
    dropped, whatever they are bound to.
    """
    from edutap.data_provider.observability import scrub_request_attributes

    class OpaqueDependency:
        def __repr__(self) -> str:
            return "<must-not-appear>"

    result = scrub_request_attributes(None, {"values": {parameter_name: OpaqueDependency()}})

    assert "must-not-appear" not in json.dumps(result, default=str)
    assert parameter_name not in result["values"]


def test_a_bare_scalar_under_an_unrecognised_name_is_dropped():
    """The other half of the Important finding: safety here cannot be name-based.

    Measured against the current mapper before this fix: a hypothetical future
    endpoint taking `person_uid` as a plain query parameter would pass it through
    verbatim, because nothing except the literal key `"body"` was ever inspected.
    A bare string carries no structure to recognise it by, so -- unlike
    `view_type`, the one specific name this module knows is safe -- nothing else
    survives merely for being a plain scalar.
    """
    from edutap.data_provider.observability import scrub_request_attributes

    result = scrub_request_attributes(None, {"values": {"person_uid": PERSON_UID}})

    assert PERSON_UID not in json.dumps(result, default=str)
    assert result["values"] == {}


def test_a_request_without_a_body_is_passed_through():
    """`/catalogue` takes a query parameter and no body; its trace stays useful."""
    from edutap.data_provider.observability import scrub_request_attributes

    attributes = {"values": {"view_type": "mensapass"}, "errors": []}

    assert scrub_request_attributes(None, attributes) == attributes


def test_an_unknown_body_shape_is_reduced_rather_than_trusted():
    """Safe by default: a value this mapper does not recognise must not survive
    unchanged, not kept because no rule here happened to match it.

    Rewritten after review found the original version of this test could not
    fail: `json.dumps(..., default=str)` on an unscrubbed object renders its
    default repr (`<Something object at 0x...>`), which never contains a class
    attribute's value regardless of whether the mapper did anything at all -- a
    completely no-op mapper passed the old assertion. This version checks
    structurally that the raw object does not survive the call, which a no-op
    mapper cannot pass.
    """
    from edutap.data_provider.observability import scrub_request_attributes

    class Something:
        secret_attribute = "must-not-appear"  # noqa: S105  a probe value, not a credential

    probe = Something()

    result = scrub_request_attributes(None, {"values": {"body": probe}})

    assert result["values"].get("body") is not probe
    assert not isinstance(result["values"].get("body"), Something)


def test_a_real_span_carries_no_person():
    """End to end, against a real exporter.

    Not redundant with the unit test above: logfire swallows an exception raised
    inside the mapper and then simply records nothing, so a mapper that crashes and
    a mapper that works are indistinguishable unless a span is actually inspected.
    Found while measuring for the design.

    The handler's body parameter is named `request` here, not `body` -- matching
    `/lookup`'s real signature (`api/routers.py`) rather than a name that happens
    to be what the first version of this mapper looked for.
    """
    from edutap.data_provider.observability import scrub_request_attributes

    exporter = InMemorySpanExporter()
    logfire.configure(
        send_to_logfire=False,
        console=False,
        additional_span_processors=[SimpleSpanProcessor(exporter)],
    )

    app = FastAPI()

    class Lookup(BaseModel):
        person_uid: str
        view_type: str
        fields: list[str]

    @app.post("/lookup")
    async def lookup(request: Lookup) -> dict:
        return {"display_name": "irrelevant"}

    logfire.instrument_fastapi(app, request_attributes_mapper=scrub_request_attributes)

    TestClient(app).post(
        "/lookup",
        json={"person_uid": PERSON_UID, "view_type": "mensapass", "fields": ["display_name"]},
    )

    spans = [json.loads(span.to_json()) for span in exporter.get_finished_spans()]
    assert spans, "no span recorded -- the mapper may have raised and been swallowed"
    blob = json.dumps(spans)
    assert PERSON_UID not in blob
    assert "mensapass" in blob, "the trace lost the information it exists for"


def test_a_real_span_from_the_real_app_carries_no_person_and_no_dependencies(
    configured_environment,
):
    """The verification bar review found missing: the mapper must be proven against
    the actual application, not a probe conveniently shaped like the brief's
    original example.

    Measured before this fix: `/lookup`'s body parameter is named `request`, not
    `body` (`api/routers.py`), so `fastapi.arguments.values` on the real app held
    the whole `config` (the view configuration), a `repository` object repr, and
    the person's uid under the key `request` -- none of it touched by a mapper
    that only ever checked for a key literally named `body`. This is what would
    have caught that: it drives `create_app()` itself, not a hand-built app, and
    asserts on the exact `values` attribute the real instrumentation produces.
    """
    from edutap.data_provider.api.app import create_app
    from edutap.data_provider.observability import scrub_request_attributes

    exporter = InMemorySpanExporter()
    logfire.configure(
        send_to_logfire=False,
        console=False,
        additional_span_processors=[SimpleSpanProcessor(exporter)],
    )

    app = create_app()
    logfire.instrument_fastapi(app, request_attributes_mapper=scrub_request_attributes)

    # The response itself is not the point -- `configured_environment` points
    # `DATABASE_URL` at a host that does not resolve, so this 500s inside the
    # handler body. The span attributes are captured during dependency solving,
    # *before* the handler runs, so they are present regardless.
    TestClient(app, raise_server_exceptions=False).post(
        "/lookup",
        headers={"Authorization": "Bearer test-token"},
        json={"person_uid": PERSON_UID, "view_type": "mensapass", "fields": ["display_name"]},
    )

    spans = exporter.get_finished_spans()
    assert spans, "no span recorded -- the mapper may have raised and been swallowed"
    lookup_spans = [span for span in spans if "fastapi.arguments.values" in span.attributes]
    assert lookup_spans, "no span carried the FastAPI arguments attribute"

    values = json.loads(lookup_spans[0].attributes["fastapi.arguments.values"])

    assert values == {"request": {"view_type": "mensapass", "field_count": 1}}, (
        "must be exactly this -- not `config` or `repository` in any form"
    )


def test_a_rejected_request_does_not_echo_the_body_through_its_error():
    """logfire records `errors` (raw Pydantic validation errors) alongside `values`,
    and this mapper only ever touched `values["body"]`.

    Found while auditing this mapper for the same class of leak it was built to
    close: on Pydantic's "missing" error type, `error["input"]` is not the missing
    field's value -- it is the *whole enclosing dict*, because the error is reported
    against the model, not the field. A `/lookup` request missing `fields` but
    carrying a `person_uid` therefore has that `person_uid` sitting in
    `errors[0]["input"]`, untouched by a mapper that only looks at `values`.
    """
    from edutap.data_provider.observability import scrub_request_attributes

    attributes = {
        "values": {},
        "errors": [
            {
                "type": "missing",
                "loc": ("body", "view_type"),
                "msg": "Field required",
                "input": {"person_uid": PERSON_UID, "fields": ["display_name"]},
                "url": "https://errors.pydantic.dev/2.13/v/missing",
            }
        ],
    }

    result = scrub_request_attributes(None, attributes)

    assert PERSON_UID not in json.dumps(result, default=str)
    assert result["errors"] == [{"type": "missing", "loc": ("body", "view_type")}]


def test_an_event_from_lookup_carries_the_pseudonym_and_not_the_person(
    sentry_events, configured_environment, monkeypatch
):
    """One person failing five times must be visible; who they are must not be."""
    from edutap.data_provider.api.app import create_app
    from edutap.data_provider.observability import ObservabilitySettings, pseudonym

    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_PSEUDONYM_SALT", "a-salt")
    from edutap.data_provider import observability

    observability.get_observability_settings.cache_clear()

    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)

    client.post(
        "/lookup",
        headers={"Authorization": "Bearer test-token"},
        json={"person_uid": PERSON_UID, "view_type": "mensapass", "fields": ["display_name"]},
    )

    blob = json.dumps(sentry_events)
    assert PERSON_UID not in blob
    expected = pseudonym(
        PERSON_UID, ObservabilitySettings(pseudonym_salt=SecretStr("a-salt")).pseudonym_salt
    )
    assert expected in blob


def test_without_a_salt_no_tag_is_attached(sentry_events, configured_environment):
    """No salt, no pseudonym -- not a tag computed from an empty key."""
    from edutap.data_provider.api.app import create_app

    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)

    client.post(
        "/lookup",
        headers={"Authorization": "Bearer test-token"},
        json={"person_uid": PERSON_UID, "view_type": "mensapass", "fields": ["display_name"]},
    )

    for event in sentry_events:
        assert "person" not in event.get("tags", {})


def test_a_real_span_from_a_rejected_request_carries_no_person():
    """End to end, mirroring `test_a_real_span_carries_no_person` for the error path.

    Measured before this half of the mapper existed: a 422 from `/lookup` with
    `view_type` missing put `person_uid` verbatim in the exported span's
    `fastapi.arguments.errors` attribute, alongside `fields` -- a plain validation
    failure, not even an exception the application raised.
    """
    from edutap.data_provider.observability import scrub_request_attributes

    exporter = InMemorySpanExporter()
    logfire.configure(
        send_to_logfire=False,
        console=False,
        additional_span_processors=[SimpleSpanProcessor(exporter)],
    )

    app = FastAPI()

    class Lookup(BaseModel):
        person_uid: str
        view_type: str
        fields: list[str]

    @app.post("/lookup")
    async def lookup(request: Lookup) -> dict:
        return {"display_name": "irrelevant"}  # pragma: no cover  never reached

    logfire.instrument_fastapi(app, request_attributes_mapper=scrub_request_attributes)

    response = TestClient(app, raise_server_exceptions=False).post(
        "/lookup",
        json={"person_uid": PERSON_UID, "fields": ["display_name"]},
    )

    assert response.status_code == 422, "the probe must exercise the validation-error path"
    spans = [json.loads(span.to_json()) for span in exporter.get_finished_spans()]
    assert spans, "no span recorded -- the mapper may have raised and been swallowed"
    blob = json.dumps(spans)
    assert PERSON_UID not in blob
    assert "missing" in blob, "the trace lost the information it exists for"
