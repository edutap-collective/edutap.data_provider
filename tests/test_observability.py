"""What may leave the process, pinned."""

import json

import pytest
import sentry_sdk
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

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

    from pydantic import BaseModel

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


def test_the_recorded_arguments_keep_the_shape_and_drop_the_person():
    """logfire records endpoint arguments on every *successful* request.

    Measured before this mapper existed: the span attribute
    `fastapi.arguments.values` held
    `{"body":{"person_uid":"u123456","view_type":"mensapass",...}}` on a plain 200.
    That is worse than the Sentry case, which only sends on an error.
    """
    from pydantic import BaseModel

    from edutap.data_provider.observability import scrub_request_attributes

    class Lookup(BaseModel):
        person_uid: str
        view_type: str
        fields: list[str]

    body = Lookup(person_uid=PERSON_UID, view_type="mensapass", fields=["display_name", "uid"])

    result = scrub_request_attributes(None, {"values": {"body": body}})

    assert PERSON_UID not in json.dumps(result, default=str)
    assert result["values"]["body"] == {"view_type": "mensapass", "field_count": 2}


def test_a_request_without_a_body_is_passed_through():
    """`/catalogue` takes a query parameter and no body; its trace stays useful."""
    from edutap.data_provider.observability import scrub_request_attributes

    attributes = {"values": {"view_type": "mensapass"}, "errors": []}

    assert scrub_request_attributes(None, attributes) == attributes


def test_an_unknown_body_shape_is_reduced_rather_than_trusted():
    """Safe by default: a future endpoint whose body this mapper does not know must
    lose its contents, not keep them because no rule matched."""
    from edutap.data_provider.observability import scrub_request_attributes

    class Something:
        secret_attribute = "must-not-appear"  # noqa: S105  a probe value, not a credential

    result = scrub_request_attributes(None, {"values": {"body": Something()}})

    assert "must-not-appear" not in json.dumps(result, default=str)


def test_a_real_span_carries_no_person(monkeypatch, tmp_path):
    """End to end, against a real exporter.

    Not redundant with the unit test above: logfire swallows an exception raised
    inside the mapper and then simply records nothing, so a mapper that crashes and
    a mapper that works are indistinguishable unless a span is actually inspected.
    Found while measuring for the design.
    """
    import logfire
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from pydantic import BaseModel

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
    async def lookup(body: Lookup) -> dict:
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


def test_a_real_span_from_a_rejected_request_carries_no_person():
    """End to end, mirroring `test_a_real_span_carries_no_person` for the error path.

    Measured before this half of the mapper existed: a 422 from `/lookup` with
    `view_type` missing put `person_uid` verbatim in the exported span's
    `fastapi.arguments.errors` attribute, alongside `fields` -- a plain validation
    failure, not even an exception the application raised.
    """
    import logfire
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from pydantic import BaseModel

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
    async def lookup(body: Lookup) -> dict:
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
