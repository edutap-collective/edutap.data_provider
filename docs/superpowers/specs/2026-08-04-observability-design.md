# Observability design — errors to Bugsink, traces and metrics over OTLP

**Date:** 2026-08-04
**Status:** agreed, not yet implemented
**Package:** `edutap.data_provider`
**Predecessor:** `docs/superpowers/specs/2026-07-30-data-provider-design.md`

## Why this is not a routine integration

Every other eduTAP service can add an error tracker by copying six lines from
`edutap.google_wallet_callback_handler`. This one cannot, because of what it holds.

The package exists to keep pass-issuing services from seeing more personal data than
they need. Its `/lookup` request body carries a `person_uid`; its response carries
directory attributes about one named human being. An error tracker is, by
construction, a machine that copies the state around a failure to a second system —
which is the one thing this service is built not to do.

The predecessor design already anticipated this in code. `create_app` raises its
`StartupError` *outside* the `except` block rather than with `raise ... from None`,
so that a pydantic `ValidationError` carrying the API token and the database password
is absent from the object graph rather than merely hidden from a printed traceback.
The recorded reason: "latent the moment Sentry or structured logging arrives."

This document is that moment.

## Decision 1: two backends, no overlapping signal

`sentry_sdk` reports **exceptions** to Bugsink. `logfire` exports **traces, metrics
and logs** over OTLP to a self-hosted collector. Nothing travels both paths.

The split is forced, not stylistic. Bugsink's own SDK guidance states that it
"intentionally does not support traces, so there is no need to send them" and that it
"does not handle metrics, traces, or other event types". `traces_sample_rate` is
therefore `0` — not a sampling decision, a statement about the receiver.

Logfire is used as a plain OTLP SDK: `send_to_logfire=False`, no Pydantic cloud
account, no token. The endpoint comes from configuration and the export is Protobuf
over HTTP.

Both halves are inert unless configured. With no DSN and no OTLP endpoint the process
behaves exactly as it does today, which is also how the test suite runs by default.

> **Note for the other eduTAP services.** `edutap.google_wallet_callback_handler` and
> `lmu_edutap_backend` both run `traces_sample_rate=1.0`. If either points at Bugsink,
> it is sending transactions to a receiver that discards them. Out of scope here;
> worth its own look.

## Decision 2: the data-protection boundary, as measured

Not reasoned from documentation — measured, by capturing the actual envelope a real
FastAPI application emits for a real request. Each row is one process, because
repeated `sentry_sdk.init()` in a single process does not give a clean reading; the
first attempt at this table disagreed with a single-case run, which is what forced the
split.

The request under test carried `Authorization: Bearer super-secret-token`,
`X-Real-Ip: 10.1.2.3`, and a body of
`{"person_uid": "u123456", "view_type": "mensapass", "fields": [...]}`.

| Configuration | API token | person_uid | client IP | view_type |
| --- | --- | --- | --- | --- |
| `send_default_pii=True` (Bugsink's recommendation) | **leaks** | **leaks** | **leaks** | leaks |
| `+ include_local_variables=False` | — | **leaks** | **leaks** | leaks |
| `+ send_default_pii=False` | — | **leaks** | — | leaks |
| `+ max_request_body_size="never"` | — | — | — | leaks |
| logfire `instrument_fastapi()`, defaults | — | **leaks** | — | leaks |
| `+ request_attributes_mapper` | — | — | — | leaks |

Three findings from that table decide the configuration.

**The scrubber does not protect the token.** With `send_default_pii=True` the
`authorization` header renders as `[Filtered]` — and the raw
`b'Bearer super-secret-token'` still appears **25 times** in the same event, inside
`exception.values[0].stacktrace.frames[*].vars.scope.headers`. Sentry sends local
variables of every stack frame by default, the ASGI scope is a local in most of them,
and the scrubber matches key *names*, not byte tuples inside a list. Only
`include_local_variables=False` closes it, and it closes it completely.

**The request body is the person_uid.** `max_request_body_size` defaults to
`"medium"`, and the `/lookup` body *is* the identifying datum. It must be `"never"`;
there is no partial version of this.

**logfire is worse than Sentry here, and it is worse all the time.** Sentry only
sends on an error. `logfire.instrument_fastapi()` writes the full validated endpoint
arguments into the span attribute `fastapi.arguments.values` on **every successful
request** — measured as
`{"body":{"person_uid":"u123456","view_type":"mensapass","fields":["display_name"]}}`.
A `request_attributes_mapper` replaces it with the *shape* of the call.

After all four Sentry options and the logfire mapper, the only remaining channel is
the **exception message itself**, and `view_type` reaching Bugsink through it is
intended. This is where the package's existing discipline pays: its messages name a
field and a view and never a value, as in *"Rule for field 'pass_valid_until' of view
'mensapass' failed on the stored data for this person."*

## Decision 3: a pseudonym, so a person is countable but not identifiable

`max_request_body_size="never"` removes the `person_uid` completely, and with it the
ability to see that the same person failed five times rather than five people failing
once. That is a real loss for an operator, and it is recoverable without a
personal datum.

Sentry events and OTel spans carry a `person` tag: the first 12 hex characters of
`HMAC-SHA256(salt, person_uid)`.

- **Keyed, not plain.** `person_uid` comes from a directory; the value space is small
  and enumerable, so a bare SHA-256 would be reversible by anyone with read access to
  Bugsink simply by hashing the directory. The salt is a secret and lives in the
  settings as `SecretStr`.
- **Truncated to 12 hex characters** — 48 bits. Enough that a collision between two
  people in one installation is not a practical concern, short enough that the tag is
  a label rather than a stored identifier.
- **Absent by default.** With no salt configured there is no tag, not a tag computed
  from an empty key. Enabling the pseudonym is a deliberate act.

The salt is per installation. Rotating it renames every pseudonym, which is the
intended property: pseudonyms do not follow a person across a rotation.

**Where it is attached.** The `person_uid` is known only inside the `/lookup` handler,
after the body has been validated — nothing earlier in the stack has it, and with
`max_request_body_size="never"` nothing later can recover it. So both attachments
happen there, on the request currently being served: `sentry_sdk.set_tag` for the
Sentry scope, and the returned mapping of the logfire `request_attributes_mapper` for
the span. `/catalogue` has no person and gets no tag.

## Component: `observability.py`

One new module, one public function, one caller.

```python
def install_observability(settings: Settings) -> None:
    """Configure error reporting and tracing, or configure nothing at all."""
```

What it does, in order: initialise `sentry_sdk` if a DSN is configured; configure
`logfire` if an OTLP endpoint is configured; return. It never raises on a backend
that is unreachable — an error tracker that prevents the service from starting has
inverted its purpose.

A second, non-public helper computes the pseudonym, so it can be tested directly:

```python
def _pseudonym(person_uid: str, salt: SecretStr | None) -> str | None:
```

The FastAPI instrumentation of logfire is applied to the app object and therefore
lives in `create_app`, not here; `observability.py` exposes the mapper function it
needs.

### Where it is called

At the very top of `create_app()`, **before** `_load_configuration()`.

That ordering is deliberate. A container that refuses to start is exactly the event an
operator most wants to see, and the predecessor design made it safe to report: the
`StartupError` message is built by `_describe()` from `loc` and `msg` only, and the
underlying pydantic error is not in the object graph. Reporting startup failures is
therefore free of the leak that would otherwise make it unthinkable.

The settings needed by `install_observability` are read by `get_settings()`, the same
`lru_cache`d call `_load_configuration()` then makes — one load, not two that could
disagree.

### Settings

Four additions to `Settings`, all optional, all inert when unset:

| Name | Type | Meaning |
| --- | --- | --- |
| `sentry_dsn` | `SecretStr \| None` | Bugsink DSN. Unset ⇒ no error reporting. |
| `otlp_endpoint` | `str \| None` | OTLP HTTP endpoint. Unset ⇒ no traces or metrics. |
| `pseudonym_salt` | `SecretStr \| None` | HMAC key. Unset ⇒ no `person` tag. |
| `environment` | `str` | `production` by default; labels events in both backends. |

`sentry_dsn` and `pseudonym_salt` are `SecretStr` for the reason `database_url`
already is: `BaseSettings.__repr__` prints every plain field verbatim, and a DSN is a
credential.

## Dependencies

`sentry-sdk[fastapi]` and `logfire[fastapi]` join `[project.dependencies]` as the
ninth and tenth runtime requirements. The predecessor design allows this only with a
written reason, so:

A service that answers a deliberately opaque 500 — opaque because the blanket handler
must not leak stored data — is a service whose failures are invisible without an error
tracker. That is not an optional quality of this deployment; it is the price of the
error contract the package chose. Making it an extra would mean the one configuration
that makes failures diagnosable is the one nobody installs by default.

The `[fastapi]` extras are not cosmetic: `logfire.instrument_fastapi()` raises at
runtime without `opentelemetry-instrumentation-fastapi`, which only that extra pulls
in. Verified by hitting exactly that error.

Consequence to accept openly: `logfire[fastapi]` brings the OpenTelemetry SDK, its
ASGI and FastAPI instrumentations, and protobuf into the container image. The image
grows. The alternative — an extra nobody enables — buys a smaller image by making the
service undebuggable.

## Tests

The suite runs today with no DSN and no endpoint, and must keep doing so unchanged.
Four new tests, in `tests/test_observability.py`:

1. **Nothing configured, nothing installed.** No DSN and no endpoint ⇒ no Sentry
   client and no logfire configuration. This is the state every other test runs in.
2. **The leak test.** A FastAPI app wired as the real one is, a fake Sentry transport,
   a request carrying token, `person_uid` and IP, and a deliberate exception. Assert
   that none of the three strings occurs anywhere in the serialised event. Written
   against the whole event as JSON rather than against named fields, because the
   token was found in a place no reasonable field list would have named.
3. **The logfire mapper.** The recorded attributes contain `view_type` and a field
   count and no `person_uid`. This test is not optional: logfire catches an exception
   raised inside the mapper internally and then simply records nothing, so a broken
   mapper looks exactly like a working one from the outside. Found while building the
   probe.
4. **The pseudonym.** Stable for one `person_uid` and salt, different across salts,
   absent when no salt is set, and never equal to the `person_uid` itself.

### One thing to verify during implementation, not to assume

`install_error_handlers` registers a handler for `Exception`. The predecessor's review
established that Starlette's `ServerErrorMiddleware` sends the response and then
re-raises unconditionally, which should let Sentry's ASGI integration see the
exception from outside. Should — that was established for a different purpose, without
Sentry in the stack. The implementation must prove at the wire level that an
unexpected 500 actually arrives in Bugsink; if it does not, the capture belongs in the
blanket handler itself.

## Documentation this obliges

Four settings that an operator must be able to find, and a data-protection boundary
that is the point of the whole design:

- `.env.example` and `compose.yml` gain the four variables, commented as optional.
- `docs/reference.md` gains them in its settings section — the suite has an anti-drift
  test asserting that every settings field is documented, so this is enforced, not
  remembered.
- `docs/explanation.md` gains the boundary: what leaves the process, what does not,
  and that the answer was measured. An operator deciding whether to point this service
  at a shared Bugsink needs that paragraph more than any other in this document.

## Out of scope

- **A correlation id in the problem document** — tying the opaque 500 to its Bugsink
  event by carrying the event id in the response. Considered and deliberately parked.
- **The uniform error contract.** FastAPI still answers a malformed body with its own
  422 shape rather than `application/problem+json`. Parked, unchanged.
- **The rule type-check gap.** `validate_config` accepts `lt()` over two `STRING`
  fields, which fails at request time. Parked, unchanged.
- **The eduTAP / LMU / EUGLOH convention review.** No written convention document
  exists in `edutap/documentation`, `edutap/ecc-documentation` or the dev setup — the
  candidates are a wallet how-to, a three-line requirements stub and an eight-line
  security note. Distilling one from the de-facto patterns is its own project in its
  own repository, and this package will be reviewed against it once it exists.
- **The same audit for the sibling services.** Both `send_default_pii=True` services
  ship their own API token to their error tracker by the mechanism measured above.
  Their repositories, their fix.
