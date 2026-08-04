# Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Report exceptions to Bugsink and export traces, metrics and logs over OTLP, without any personal datum or credential leaving the process.

**Architecture:** One new module, `observability.py`, owns its own optional settings, the Sentry options, the logfire configuration and the pseudonym function. `create_app` calls its single public entry point before it resolves anything else. The `/lookup` handler is the only place that sees a `person_uid`, so it is the only place that attaches the pseudonym.

**Tech Stack:** Python 3.12+, FastAPI, pydantic-settings, `sentry-sdk[fastapi]`, `logfire[fastapi]`, pytest.

**Spec:** `docs/superpowers/specs/2026-08-04-observability-design.md`

## Global Constraints

- Python `>=3.12`; tox over 3.12, 3.13, 3.14.
- Licence EUPL-1.2; docs, code comments and commit messages in **English**.
- **The service stays read-only.** Nothing in this plan touches the repository or the database.
- Both backends are **inert unless configured**. With no DSN and no OTLP endpoint the process must behave exactly as it does today, and the existing 144 tests must keep passing unchanged.
- Sentry options, fixed, all five together: `traces_sample_rate=0`, `send_default_pii=False`, `include_local_variables=False`, `max_request_body_size="never"`, `environment=<setting>`. Each was measured; none is a preference.
- An error tracker must never prevent the service from starting. No configuration of a backend may raise out of `install_observability`.
- Test-first for every behaviour: failing test, confirm the failure, then implement.
- `ruff check src tests`, `ruff format --check src tests` and `ty check src` clean at the end of every task.

## Two corrections to the spec, with reasons

**1. The four settings live in their own model, not in `Settings`.**
The spec asks for `install_observability` to run *before* `_load_configuration()`, so that a process refusing to start is visible in Bugsink. It also puts the four fields on `Settings`. Those cannot both hold: if `Settings` fails to validate — the very case worth reporting — there is no way to read the DSN out of it. So `observability.py` defines its own `ObservabilitySettings` with four optional fields and no required one, which therefore always constructs. `Settings` is unchanged.

**2. `pseudonym` is public, not `_pseudonym`.**
The spec names it `_pseudonym`. It is called from `api/routers.py`, and a leading underscore that another module imports is a lie about the boundary.

## File Structure

| File | Responsibility |
|---|---|
| `src/edutap/data_provider/observability.py` | **new** — `ObservabilitySettings`, `get_observability_settings`, `sentry_options`, `scrub_request_attributes`, `pseudonym`, `install_observability` |
| `src/edutap/data_provider/api/app.py` | calls `install_observability` first; instruments the app |
| `src/edutap/data_provider/api/routers.py` | attaches the pseudonym in `/lookup` |
| `pyproject.toml` | two new runtime dependencies |
| `tests/conftest.py` | clears the four new variables and the new settings cache |
| `tests/test_observability.py` | **new** — the leak test, the mapper test, the pseudonym tests |
| `tests/test_settings.py` | the inert default |
| `tests/test_docs.py` | anti-drift over the new settings model |
| `docs/reference.md`, `docs/explanation.md`, `.env.example`, `compose.yml`, `CHANGES.md` | operator-facing record |

---

### Task 1: The settings model, inert and documented

Nothing is installed yet and no dependency is added. This task only creates a settings model that always constructs, and the documentation the suite enforces.

**Files:**
- Create: `src/edutap/data_provider/observability.py`
- Modify: `tests/conftest.py`, `docs/reference.md`, `.env.example`, `compose.yml`
- Test: `tests/test_settings.py`, `tests/test_docs.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ObservabilitySettings` with fields `sentry_dsn: SecretStr | None`, `otlp_endpoint: str | None`, `pseudonym_salt: SecretStr | None`, `environment: str`; and `get_observability_settings() -> ObservabilitySettings`, `lru_cache`d.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_settings.py`:

```python
def test_observability_is_off_when_nothing_is_configured():
    """The default is a service that reports nowhere.

    Every one of the other tests in this suite runs in this state, so if the
    default were anything else they would all be emitting.
    """
    from edutap.data_provider.observability import ObservabilitySettings

    settings = ObservabilitySettings()

    assert settings.sentry_dsn is None
    assert settings.otlp_endpoint is None
    assert settings.pseudonym_salt is None
    assert settings.environment == "production"


def test_the_observability_settings_never_refuse_to_build(monkeypatch):
    """No field is required, on purpose.

    `create_app` reads these *before* it resolves `Settings`, so that a process
    refusing to start is still reported. A required field here would make the
    reporting of a broken configuration itself depend on a working configuration.
    """
    from edutap.data_provider.observability import ObservabilitySettings

    for name in ("DATABASE_URL", "CONFIG_PATH", "API_TOKEN"):
        monkeypatch.delenv(f"EDUTAP_DATA_PROVIDER_{name}", raising=False)

    assert ObservabilitySettings() is not None


def test_the_dsn_and_the_salt_are_secrets(monkeypatch):
    """Neither may appear in a repr, for the reason `database_url` is a secret."""
    from edutap.data_provider.observability import ObservabilitySettings

    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_SENTRY_DSN", "https://public@bugsink.invalid/7")
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_PSEUDONYM_SALT", "a-real-salt")

    rendered = repr(ObservabilitySettings())

    assert "public@bugsink.invalid" not in rendered
    assert "a-real-salt" not in rendered
```

Replace `test_every_setting_is_documented` in `tests/test_docs.py` with a version covering both models:

```python
def test_every_setting_is_documented():
    """Both settings models, not only the required one.

    `ObservabilitySettings` decides what leaves the process. An operator who
    cannot find it in the reference cannot decide whether to enable it.
    """
    from edutap.data_provider.observability import ObservabilitySettings
    from edutap.data_provider.settings import Settings

    reference = (DOCS / "reference.md").read_text()
    for model in (Settings, ObservabilitySettings):
        for field in model.model_fields:
            assert f"EDUTAP_DATA_PROVIDER_{field.upper()}" in reference
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_settings.py tests/test_docs.py -v`
Expected: the three new tests FAIL with `ModuleNotFoundError: No module named 'edutap.data_provider.observability'`, and `test_every_setting_is_documented` fails the same way.

- [ ] **Step 3: Write the settings model**

Create `src/edutap/data_provider/observability.py`:

```python
"""Error reporting and tracing, and the boundary of what may leave the process.

The service exists to keep pass-issuing consumers from seeing more personal data
than they need. An error tracker is a machine that copies the state around a
failure to a second system, which is the one thing the service is built not to do,
so every option here was chosen against a measurement of what actually reaches the
wire rather than from a backend's recommendation. The measurements are recorded in
`docs/superpowers/specs/2026-08-04-observability-design.md`.
"""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


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
```

- [ ] **Step 4: Teach the test fixtures about the new variables**

In `tests/conftest.py`, extend `_ENVIRONMENT`:

```python
_ENVIRONMENT = (
    "EDUTAP_DATA_PROVIDER_DATABASE_URL",
    "EDUTAP_DATA_PROVIDER_CONFIG_PATH",
    "EDUTAP_DATA_PROVIDER_API_TOKEN",
    "EDUTAP_DATA_PROVIDER_ECHO_SQL",
    # Without these four a developer with a DSN in their shell would have every
    # test in this suite reporting to a real Bugsink, and the suite would pass.
    "EDUTAP_DATA_PROVIDER_SENTRY_DSN",
    "EDUTAP_DATA_PROVIDER_OTLP_ENDPOINT",
    "EDUTAP_DATA_PROVIDER_PSEUDONYM_SALT",
    "EDUTAP_DATA_PROVIDER_ENVIRONMENT",
)
```

and in the same fixture, beside the other three cache clears (both before the `yield` and after it):

```python
    from edutap.data_provider import observability

    observability.get_observability_settings.cache_clear()
```

- [ ] **Step 5: Document the four settings**

In `docs/reference.md`, in the `## Settings` table, after the `ECHO_SQL` row:

```markdown
| `EDUTAP_DATA_PROVIDER_SENTRY_DSN` | secret string | unset | Bugsink DSN. Unset means no error reporting at all. Held as a secret: a DSN is a credential |
| `EDUTAP_DATA_PROVIDER_OTLP_ENDPOINT` | string | unset | OTLP over HTTP endpoint for traces, metrics and logs. Unset means no export |
| `EDUTAP_DATA_PROVIDER_PSEUDONYM_SALT` | secret string | unset | HMAC key behind the `person` tag on events and spans. Unset means no such tag. A directory is enumerable, so an unkeyed hash would be reversible by anyone reading the error tracker |
| `EDUTAP_DATA_PROVIDER_ENVIRONMENT` | string | `production` | labels events and spans in both backends |
```

In `.env.example`, at the end:

```
# Observability. All four optional; with none of them set, nothing is reported
# anywhere and no span leaves the process.
# EDUTAP_DATA_PROVIDER_SENTRY_DSN=https://public@bugsink.example/1
# EDUTAP_DATA_PROVIDER_OTLP_ENDPOINT=http://collector:4318
# EDUTAP_DATA_PROVIDER_PSEUDONYM_SALT=change-me-per-installation
# EDUTAP_DATA_PROVIDER_ENVIRONMENT=development
```

In `compose.yml`, in the `app` service's `environment` block:

```yaml
      # Optional; unset in the test environment, so nothing is reported anywhere.
      EDUTAP_DATA_PROVIDER_SENTRY_DSN: ${EDUTAP_DATA_PROVIDER_SENTRY_DSN:-}
      EDUTAP_DATA_PROVIDER_OTLP_ENDPOINT: ${EDUTAP_DATA_PROVIDER_OTLP_ENDPOINT:-}
      EDUTAP_DATA_PROVIDER_ENVIRONMENT: development
```

- [ ] **Step 6: Run the whole suite and the linters**

Run: `.venv/bin/python -m pytest -v` — expected: 147 passed, 5 deselected, no warnings.
Run: `.venv/bin/python -m ruff check src tests && .venv/bin/python -m ruff format --check src tests && .venv/bin/python -m ty check src` — expected: clean.

An empty-string DSN from the compose default deserves one check, because `${VAR:-}` sets the variable to the empty string rather than leaving it unset:

Run: `EDUTAP_DATA_PROVIDER_SENTRY_DSN= .venv/bin/python -c "from edutap.data_provider.observability import ObservabilitySettings; print(repr(ObservabilitySettings().sentry_dsn))"`
Expected: `SecretStr('**********')` wrapping an empty string, **not** `None`. Note the value for Task 3 — an empty DSN must not count as configured.

- [ ] **Step 7: Commit**

```bash
git add src/edutap/data_provider/observability.py tests/conftest.py tests/test_settings.py tests/test_docs.py docs/reference.md .env.example compose.yml
git commit -m "feat: add the observability settings, off by default"
```

---

### Task 2: The pseudonym

A pure function, no dependency, no I/O. It exists so an operator can see that one person failed five times without learning who.

**Files:**
- Modify: `src/edutap/data_provider/observability.py`
- Test: `tests/test_observability.py` (create)

**Interfaces:**
- Consumes: `ObservabilitySettings` from Task 1.
- Produces: `pseudonym(person_uid: str, salt: SecretStr | None) -> str | None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_observability.py`:

```python
"""What may leave the process, pinned."""

import pytest
from pydantic import SecretStr

from edutap.data_provider.observability import pseudonym

SALT = SecretStr("a-salt")
OTHER_SALT = SecretStr("another-salt")


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_observability.py -v`
Expected: collection error — `ImportError: cannot import name 'pseudonym'`.

- [ ] **Step 3: Write the implementation**

Add to `src/edutap/data_provider/observability.py`, after the imports (`import hashlib` and `import hmac` at the top):

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_observability.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add src/edutap/data_provider/observability.py tests/test_observability.py
git commit -m "feat: add a keyed pseudonym for a person"
```

---

### Task 3: Sentry, and the test that proves nothing leaks

The task that carries the whole design. It adds the first dependency, the five options, and the test that would have caught the token leak.

**Files:**
- Modify: `pyproject.toml`, `src/edutap/data_provider/observability.py`, `src/edutap/data_provider/api/app.py`
- Test: `tests/test_observability.py`

**Interfaces:**
- Consumes: `ObservabilitySettings`, `get_observability_settings` from Task 1.
- Produces: `sentry_options(settings: ObservabilitySettings) -> dict[str, object]` and `install_observability(settings: ObservabilitySettings) -> None`.

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`, in `[project.dependencies]`, after `"pyyaml>=6",`:

```toml
    # The ninth runtime dependency, which the design record requires a written reason
    # for. A service that answers a deliberately opaque 500 -- opaque because the
    # blanket handler must not leak stored data -- has no diagnosable failure without
    # an error tracker. Making it an extra would mean the one configuration that
    # makes failures visible is the one nobody installs.
    "sentry-sdk[fastapi]>=2.66",
```

Run: `uv pip install -U -e ".[dev]"`

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_observability.py`:

```python
import json

import sentry_sdk
from fastapi import FastAPI
from fastapi.testclient import TestClient

from edutap.data_provider.observability import ObservabilitySettings, sentry_options

TOKEN = "super-secret-token"  # noqa: S105  a probe value, not a credential
PERSON_UID = "u123456"
CLIENT_IP = "10.1.2.3"


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
    sentry_sdk.init(dsn=None)


def _probe_app() -> FastAPI:
    """An application shaped like the real one where it matters: a body carrying a
    person, and a handler that fails after the body has been read."""
    from pydantic import BaseModel

    app = FastAPI()

    class Lookup(BaseModel):
        person_uid: str
        view_type: str
        fields: list[str]

    @app.post("/lookup")
    async def lookup(body: Lookup) -> dict:
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


def test_an_empty_dsn_does_not_count_as_configured():
    """compose.yml writes `${VAR:-}`, which sets the variable to the empty string
    rather than leaving it unset. An empty DSN must mean off, not a broken client."""
    from edutap.data_provider.observability import install_observability

    install_observability(ObservabilitySettings(sentry_dsn=SecretStr("")))

    assert not sentry_sdk.get_client().is_active()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_observability.py -v`
Expected: collection error — `ImportError: cannot import name 'sentry_options'`.

- [ ] **Step 4: Write the implementation**

Add to `src/edutap/data_provider/observability.py` (with `import sentry_sdk` at the top):

```python
def sentry_options(settings: ObservabilitySettings) -> dict[str, object]:
    """The options that decide what leaves the process.

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
    its own purpose, so an unreachable or misconfigured backend must cost telemetry
    and nothing else.
    """
    dsn = settings.sentry_dsn.get_secret_value() if settings.sentry_dsn else ""
    if dsn:
        sentry_sdk.init(dsn=dsn, **sentry_options(settings))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_observability.py -v`
Expected: all pass. If `test_no_credential_and_no_person_reaches_the_error_tracker` fails, the option set is wrong — do not weaken the test.

- [ ] **Step 6: Prove the test can fail**

A leak test that cannot go red is decoration. Temporarily drop `"include_local_variables": False` from `sentry_options`, run the test, confirm it FAILS on the token, then restore the line and confirm it passes again. Do not commit the mutation.

- [ ] **Step 7: Wire it into the application factory**

In `src/edutap/data_provider/api/app.py`, import `get_observability_settings` and `install_observability` from `..observability`, and make `create_app` begin with them:

```python
def create_app() -> FastAPI:
    """Build the FastAPI application, or refuse to build a misconfigured one."""
    # First, before the settings this service needs to run are even resolved. A
    # process that refuses to start is exactly the event an operator wants to see,
    # and reporting it is safe here: `_describe` renders only `loc` and `msg`, and
    # the pydantic error carrying the token and the DSN is not in the object graph.
    install_observability(get_observability_settings())
    _load_configuration()
    app = FastAPI(title="eduTAP data provider", version="0.1.0")
    install_error_handlers(app)
    app.include_router(health_router)
    app.include_router(router)
    return app
```

- [ ] **Step 8: Verify what the spec said to verify, not to assume**

`install_error_handlers` registers a handler for `Exception`. The predecessor's review established that Starlette's `ServerErrorMiddleware` re-raises after responding — established without Sentry in the stack. Prove it end to end rather than trusting it.

Add to `tests/test_observability.py`:

```python
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

    async def explode(*args, **kwargs):
        raise RuntimeError("something no handler expected")

    monkeypatch.setattr(routers, "catalogue_for", explode)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get(
        "/catalogue", params={"view_type": "mensapass"}, headers={"Authorization": "Bearer test-token"}
    )

    assert response.status_code == 500
    types = [
        value["type"]
        for event in sentry_events
        for value in event.get("exception", {}).get("values", [])
    ]
    assert "RuntimeError" in types, "the blanket handler swallowed the report"
```

Run: `.venv/bin/python -m pytest tests/test_observability.py -v`

If this test fails, the capture does not happen by itself and belongs in the blanket handler in `api/errors.py`, as an explicit `sentry_sdk.capture_exception(exception)` before the problem document is built. Implement that only if the test proves it necessary, and say so in the commit message either way.

- [ ] **Step 9: Run everything**

Run: `.venv/bin/python -m pytest -v` — expected: all pass, no warnings.
Run: `.venv/bin/python -m ruff check src tests && .venv/bin/python -m ruff format --check src tests && .venv/bin/python -m ty check src`

- [ ] **Step 10: Commit**

```bash
git add pyproject.toml src/edutap/data_provider/observability.py src/edutap/data_provider/api/app.py tests/test_observability.py
git commit -m "feat: report exceptions to Bugsink without a credential or a person"
```

---

### Task 4: OTLP through logfire, with the request body reduced to its shape

logfire is the more dangerous half: Sentry only sends on an error, while logfire's FastAPI instrumentation records endpoint arguments on **every successful request**.

**Files:**
- Modify: `pyproject.toml`, `src/edutap/data_provider/observability.py`, `src/edutap/data_provider/api/app.py`
- Test: `tests/test_observability.py`

**Interfaces:**
- Consumes: `install_observability` from Task 3.
- Produces: `scrub_request_attributes(request, attributes) -> dict`, passed to `logfire.instrument_fastapi` by `create_app`.

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`, after the `sentry-sdk` entry:

```toml
    # The tenth runtime dependency; same reason as the ninth. The [fastapi] extra is
    # not cosmetic: `logfire.instrument_fastapi()` raises at runtime without
    # `opentelemetry-instrumentation-fastapi`, which only that extra pulls in.
    "logfire[fastapi]>=4.39",
```

Run: `uv pip install -U -e ".[dev]"`

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_observability.py`:

```python
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
        secret_attribute = "must-not-appear"

    result = scrub_request_attributes(None, {"values": {"body": Something()}})

    assert "must-not-appear" not in json.dumps(result, default=str)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_observability.py -v`
Expected: `ImportError: cannot import name 'scrub_request_attributes'`.

- [ ] **Step 4: Write the implementation**

Add to `src/edutap/data_provider/observability.py`:

```python
def scrub_request_attributes(request: object, attributes: dict) -> dict:
    """Replace a recorded request body with the shape of the call.

    logfire's FastAPI instrumentation records the validated endpoint arguments as a
    span attribute on every request, successful ones included. For `/lookup` those
    arguments are a `person_uid`, so the raw mapping cannot be exported.

    What survives is what makes a trace worth having -- which view was asked for and
    how many fields -- and not who was asked about. A body this function does not
    recognise is reduced to nothing rather than passed through: a later endpoint
    must not become an export path because no rule here happened to match it.
    """
    values = attributes.get("values")
    if not isinstance(values, dict) or "body" not in values:
        return attributes

    body = values["body"]
    reduced = {
        "view_type": getattr(body, "view_type", None),
        "field_count": len(getattr(body, "fields", None) or []),
    }
    return {**attributes, "values": {**values, "body": reduced}}
```

and extend `install_observability`:

```python
    if settings.otlp_endpoint:
        logfire.configure(
            # No Pydantic cloud account and no token: this is logfire used as a
            # plain OTLP SDK against a self-hosted collector.
            send_to_logfire=False,
            service_name="edutap.data_provider",
            environment=settings.environment,
            console=False,
        )
```

with `import logfire` and `import os` at the top.

The endpoint itself is read by the OpenTelemetry SDK from `OTEL_EXPORTER_OTLP_ENDPOINT` rather than from an argument, so it has to be placed there before `logfire.configure` runs — inside the same `if`, as the first statement of the block:

```python
        # The exporter takes its endpoint from the OpenTelemetry environment, not
        # from an argument. Writing it here keeps the package's own configuration in
        # pydantic-settings, where every other value lives, instead of asking an
        # operator to set one variable in our namespace and one in OpenTelemetry's.
        # `setdefault`, not assignment: an operator who has set the OTel variable
        # deliberately -- alongside the protocol, header and timeout variables the
        # SDK also reads -- keeps their value.
        os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", settings.otlp_endpoint)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_observability.py -v`
Expected: all pass.

- [ ] **Step 6: Instrument the application**

In `create_app`, after the routers are included:

```python
    # Only when tracing is configured: `instrument_fastapi` patches the application
    # whether or not an exporter exists, and an unexported span is still work done on
    # every request.
    if get_observability_settings().otlp_endpoint:
        logfire.instrument_fastapi(app, request_attributes_mapper=scrub_request_attributes)
```

- [ ] **Step 7: Verify the mapper end to end, because a broken one is silent**

logfire catches an exception raised inside the mapper internally and then records nothing at all — so a mapper with a bug looks exactly like a working one from the outside. Prove the wiring with a real span.

Add to `tests/test_observability.py`:

```python
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
```

If `logfire.configure` leaking into later tests turns out to be a problem — a symptom would be unrelated tests recording spans — add a fixture that reconfigures with `send_to_logfire=False, console=False` and no processors at teardown, and note it in the ledger.

- [ ] **Step 8: Run everything**

Run: `.venv/bin/python -m pytest -v` — expected: all pass, no warnings. Confirm the count against Task 3's, and that no pre-existing test changed its result.
Run: `.venv/bin/python -m ruff check src tests && .venv/bin/python -m ruff format --check src tests && .venv/bin/python -m ty check src`

Also confirm the image still builds with two more dependencies in it:

Run: `docker build -t edutap-data-provider:local . && docker run --rm edutap-data-provider:local python -c "import edutap.data_provider"`

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml src/edutap/data_provider/observability.py src/edutap/data_provider/api/app.py tests/test_observability.py
git commit -m "feat: export traces over OTLP with the request body reduced to its shape"
```

---

### Task 5: The person tag, and the operator-facing record

The pseudonym from Task 2 is not attached to anything yet. `/lookup` is the only place that holds a `person_uid`, and with `max_request_body_size="never"` nothing downstream can recover it.

**Files:**
- Modify: `src/edutap/data_provider/api/routers.py`, `src/edutap/data_provider/observability.py`, `docs/explanation.md`, `CHANGES.md`
- Test: `tests/test_observability.py`

**Interfaces:**
- Consumes: `pseudonym` (Task 2), `get_observability_settings` (Task 1), `scrub_request_attributes` (Task 4).
- Produces: nothing new; this task attaches what earlier tasks built.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_observability.py`:

```python
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
    expected = pseudonym(PERSON_UID, ObservabilitySettings(pseudonym_salt=SecretStr("a-salt")).pseudonym_salt)
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
```

These two need the request to reach the handler and fail there. `configured_environment` gives a view named `mensapass` with a `display_name` field, and no database, so the repository call fails — which is the failure that produces the event. Confirm that assumption when the test first runs; if the request fails earlier than the tag is set, move the `set_tag` call ahead of the repository call and say so in the commit message.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_observability.py -v`
Expected: both FAIL — the pseudonym is nowhere in the event.

- [ ] **Step 3: Attach the tag in the handler**

In `src/edutap/data_provider/api/routers.py`, at the top of `lookup`, before any other work:

```python
    # The only place in the process that holds a person_uid. Sentry is configured
    # with max_request_body_size="never", so nothing downstream can recover it -- and
    # nothing downstream should. What survives is a keyed pseudonym: enough to see
    # that one person failed repeatedly, not enough to learn who.
    tag = pseudonym(request.person_uid, get_observability_settings().pseudonym_salt)
    if tag is not None:
        sentry_sdk.set_tag("person", tag)
```

with `import sentry_sdk` and `from ..observability import get_observability_settings, pseudonym` added to the imports.

- [ ] **Step 4: Attach it to the span as well**

In `scrub_request_attributes`, extend the reduced body so a trace carries the same label as an event:

```python
    reduced = {
        "view_type": getattr(body, "view_type", None),
        "field_count": len(getattr(body, "fields", None) or []),
    }
    person_uid = getattr(body, "person_uid", None)
    if person_uid is not None:
        tag = pseudonym(person_uid, get_observability_settings().pseudonym_salt)
        if tag is not None:
            reduced["person"] = tag
```

Update `test_the_recorded_arguments_keep_the_shape_and_drop_the_person` from Task 4: it runs with no salt configured, so the expected mapping is unchanged. Confirm that rather than assume it — if the test now fails, the settings cache is holding a salt from another test and the fixture needs the clear.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_observability.py -v`
Expected: all pass.

- [ ] **Step 6: Write the paragraph an operator actually needs**

In `docs/explanation.md`, a new section. The reference lists the settings; this says what turning them on means:

```markdown
## What leaves the process, and what does not

The service exists so that a consumer sees only the fields it needs. An error
tracker is a machine that copies the state around a failure somewhere else, so
pointing one at this service is a decision about personal data, not a piece of
operations plumbing.

The answer was measured rather than assumed, against the envelope a real request
actually produces. Three things were true of the recommended configuration and are
now false:

* The bearer token appeared in every event, dozens of times over, inside the local
  variables of the stack frames — while the `Authorization` header itself rendered
  as `[Filtered]`. Local variables are no longer sent.
* The `/lookup` request body was sent, and for this service the body *is* the
  identifying datum. Request bodies are no longer sent.
* The tracing integration recorded the validated request body on every *successful*
  request, not only on failures. It now records the view and the number of fields.

What reaches an error tracker is therefore: the exception and its stack, the view
type, the name of a field, and — only if a salt is configured — a keyed pseudonym of
the person. What never reaches it: the API token, the database password, the
`person_uid`, the client's IP address, and any stored value.

The one remaining channel is the text of an exception message, which is why the
messages this service writes name a field and a view and never a value.

The pseudonym is an HMAC under a per-installation salt, truncated to 12 hex
characters. An unkeyed hash would not do: a `person_uid` comes from a directory, so
anyone able to read the error tracker could hash the directory and undo it. Rotating
the salt renames every pseudonym, which is intended — a pseudonym should not follow a
person for ever.
```

- [ ] **Step 7: Record the change**

In `CHANGES.md`, under `## 0.1.0 (unreleased)`:

```markdown
- Optional error reporting to Bugsink and OTLP export of traces, metrics and logs,
  both off unless configured. No credential, no `person_uid`, no client address and
  no stored value leaves the process; a keyed pseudonym stands in for a person.
```

- [ ] **Step 8: Run everything, including the parts CI runs**

Run: `.venv/bin/python -m pytest -v`
Run: `.venv/bin/python -m pytest -m integration -v`
Run: `.venv/bin/python -m ruff check src tests && .venv/bin/python -m ruff format --check src tests && .venv/bin/python -m ty check src`
Run: `.venv/bin/python -m sphinx -E -W docs docs/_build/html` — `-W` turns a warning into an error, so this must be silent.
Run: `docker build -t edutap-data-provider:local . && docker run --rm edutap-data-provider:local python -c "import edutap.data_provider"`

- [ ] **Step 9: Commit**

```bash
git add src/edutap/data_provider/api/routers.py src/edutap/data_provider/observability.py tests/test_observability.py docs/explanation.md CHANGES.md
git commit -m "feat: label events and spans with a keyed pseudonym of the person"
```

---

## Verification for the whole branch

- [ ] `tox` over py312, py313, py314 plus lint — the matrix, not only the local interpreter.
- [ ] Every test in `tests/test_observability.py` proven able to fail, by mutating the thing it guards and watching it go red. A leak test that cannot go red is decoration.
- [ ] `git grep -n "person_uid" src/` — every hit is either the request model, the repository call, or the pseudonym call. No third place.
- [ ] The service starts and answers with both backends configured against endpoints that do not exist, proving `install_observability` never raises:
      `EDUTAP_DATA_PROVIDER_SENTRY_DSN=https://public@127.0.0.1:1/1 EDUTAP_DATA_PROVIDER_OTLP_ENDPOINT=http://127.0.0.1:1 make run`
      then `curl -s localhost:8000/healthz` must answer `{"status":"ok"}`.
