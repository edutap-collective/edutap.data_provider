# Reference

Everything the service exposes. Version 0.1.0.

## HTTP API

Base URL is the service root. `GET /healthz` is open; every other endpoint requires
the bearer token from `EDUTAP_DATA_PROVIDER_API_TOKEN`:

```text
Authorization: Bearer <token>
```

How the header is checked:

* The scheme is split off the credential and matched **case-insensitively**, as
  RFC 7235 requires: `bearer`, `Bearer` and `BEARER` are the same scheme. Anything
  else — another scheme, no scheme at all — is refused.
* Only the credential is compared with the configured token, and that comparison
  runs in constant time. The scheme is public framing, not a secret.
* An **empty** credential is refused before any comparison happens. Without that,
  `compare_digest("", "")` would be true and an empty configured token would degrade
  into "no credential needed". A deployment cannot reach that state in the first
  place — an empty `EDUTAP_DATA_PROVIDER_API_TOKEN` [stops the process at
  startup](#startup) — but the check holds the invariant where it is enforced,
  rather than trusting a constraint declared in another module.
* Every failure — no header, wrong scheme, wrong token — produces the same 401 and
  the same message. A caller cannot tell them apart.

FastAPI also serves the generated OpenAPI document at `/openapi.json` and its
interactive form at `/docs`.

### `GET /healthz`

No authentication, no parameters.

| Status | Media type | Body |
|---|---|---|
| 200 | `application/json` | `{"status": "ok"}` |

It reports that the process is up: liveness, not readiness. Answering at all already
carries information, because the process only exists if its settings and its view
configuration loaded — see [startup](#startup). It says nothing about the database:
nothing on this path opens a connection, so a service whose database is unreachable
still answers `{"status": "ok"}` here and fails a `/lookup` with a 500.

### `GET /catalogue`

| Query parameter | Type | Required | Meaning |
|---|---|---|---|
| `view_type` | string | yes | the configured view whose field list you want |

Answers with the field list of that view, sorted by `key`:

```json
[
  {"key": "display_name", "kinds": ["STRING", "TEXT"], "derived": false, "description": null},
  {"key": "pass_valid_until", "kinds": ["STRING", "TEXT", "DATETIME"], "derived": true,
   "description": "At most seven days ahead, never past the role that carries it"}
]
```

| Entry field | Type | Meaning |
|---|---|---|
| `key` | string | the field name a `/lookup` call may ask for |
| `kinds` | list of [field kind](#field-kinds) | what the field is good for |
| `derived` | boolean | `true` when the value is computed at read time, `false` when a producer wrote it |
| `description` | string or `null` | the description from the configuration, if any |

Fields a row carries but the configuration never mentions do not appear here, and
`/lookup` will not return them.

| Status | Condition |
|---|---|
| 200 | the view is configured |
| 401 | missing or wrong bearer token |
| 404 | `view_type` is not configured |
| 422 | `view_type` is absent from the query string (FastAPI's own shape, see [errors](#errors)) |

### `POST /lookup`

Request body, `application/json`:

| Field | Type | Meaning |
|---|---|---|
| `person_uid` | string | the person identifier as the producer wrote it |
| `view_type` | string | the configured view to read |
| `fields` | list of string | exactly the fields you want back |

```json
{"person_uid": "a@example.edu", "view_type": "mensapass",
 "fields": ["display_name", "pass_valid_until"]}
```

The answer is a flat object with the requested fields:

```json
{"display_name": "Alex Example", "pass_valid_until": "2026-08-07"}
```

Rules of the projection:

* Only the requested fields are returned; the row's other fields are not.
* A field the catalogue does not offer is an error, not a silent omission.
* A field the catalogue offers but that is `null` or absent for this person is
  simply absent from the answer.
* Derived fields are evaluated for this request. A value with a date type is
  serialised as an ISO 8601 string.

| Status | Condition |
|---|---|
| 200 | the row exists and every requested field is offered |
| 400 | at least one requested field is not in this view's catalogue |
| 401 | missing or wrong bearer token |
| 404 | `view_type` is not configured, or no row exists for `(person_uid, view_type)` |
| 422 | the request body does not match the model (FastAPI's own shape, see [errors](#errors)) |
| 500 | a derivation rule failed on this person's stored data |

There is no search endpoint, no person listing and no write path.

### Errors

Two body shapes exist, and a consumer must handle both.

**Everything raised inside a route or a dependency** becomes a problem document with
media type `application/problem+json`:

```json
{"title": "Unknown field", "status": 400, "detail": "View 'mensapass' does not offer: salary."}
```

| `title` | Status | Raised when |
|---|---|---|
| `Unauthorized` | 401 | the `Authorization` header does not carry the configured token under the `Bearer` scheme — see [above](#http-api) for what is and is not accepted |
| `Unknown view type` | 404 | the requested `view_type` is not in the configuration |
| `Unknown field` | 400 | `fields` names something the catalogue does not offer |
| `Unknown person` | 404 | no row exists for `(person_uid, view_type)` |
| `Derived field cannot be computed` | 500 | a rule raised on the stored data, e.g. a `DATETIME` field holding `02.08.2026` |
| `Internal server error` | 500 | any unanticipated exception |

The last one carries a fixed detail, *The request could not be completed because of
an internal error.*, and says nothing else on purpose: an arbitrary exception's
message can quote stored personal data, and so can its type name. The traceback goes
to the server log instead.

`Derived field cannot be computed` is a 500 rather than a 4xx deliberately: the
request was well-formed and no different request would succeed, so the defect — and
the retry semantics — belong on the server side.

**Failures FastAPI produces before a route is entered** keep FastAPI's own shape:
status 422, media type `application/json`, and a `detail` *list*:

```json
{"detail": [{"type": "missing", "loc": ["body", "view_type"], "msg": "Field required",
             "input": {"person_uid": "a@example.edu"}}]}
```

A 404 for a path that matches no route is likewise FastAPI's own, not a problem
document.

## Settings

Process configuration, through pydantic-settings. Every name carries the prefix
`EDUTAP_DATA_PROVIDER_`; a `.env` file in the working directory is read, and unknown
variables are ignored.

| Variable | Type | Default | Meaning |
|---|---|---|---|
| `EDUTAP_DATA_PROVIDER_DATABASE_URL` | secret string | — required | SQLAlchemy async URL, e.g. `postgresql+asyncpg://user:password@host/database`. The account needs `SELECT` and nothing more. A DSN carries the password in clear text, so the value is held as a secret and does not appear in a settings repr, a traceback or a log line |
| `EDUTAP_DATA_PROVIDER_CONFIG_PATH` | path | — required | the view configuration file, read and validated once at startup |
| `EDUTAP_DATA_PROVIDER_API_TOKEN` | secret string | — required | the bearer token every API call must present. Must not be empty: an empty token authenticates nobody, so the process refuses to start |
| `EDUTAP_DATA_PROVIDER_ECHO_SQL` | boolean | `false` | log every statement the engine emits; development only |

## Startup

`create_app` resolves the settings and the view configuration while it builds the
application, before the server binds a port. Neither is left to the first request: a
process whose configuration is unusable must not start, answer `/healthz` and satisfy
a health-check-based deployment while every real request fails.

Fatal, therefore:

* a required variable is missing;
* `EDUTAP_DATA_PROVIDER_API_TOKEN` is present but empty;
* the view configuration is missing, is not valid YAML, or fails any of the checks
  listed under [view configuration](#view-configuration).

The failure is an `edutap.data_provider.api.app.StartupError`, and the process does
not come up. What an operator sees for a missing variable:

```text
edutap.data_provider.api.app.StartupError: The service cannot start: its settings are unusable.

  EDUTAP_DATA_PROVIDER_CONFIG_PATH: Field required

Set these in the environment or in a .env file next to the process. No value is shown above on purpose: the settings carry the API token and the database password.
```

and for a view configuration the startup type check refuses:

```text
edutap.data_provider.api.app.StartupError: The service cannot start: the view configuration is unusable.

  Invalid view configuration:
  mensapass.pass_valid_until: add_days() needs a date, but 'display_name' does not declare DATETIME.
```

No setting value appears in either message, and pydantic's own `ValidationError` is
deliberately kept out of the traceback: it renders the raw settings mapping — every
value as it was read, before `SecretStr` ever sees it — so one missing variable would
otherwise print the API token and the database password into the startup log.

## View configuration

One YAML file, its path from `EDUTAP_DATA_PROVIDER_CONFIG_PATH`. `views.example.yaml`
in the repository root is a complete working example.

```yaml
constants:
  open_ended: 9999-12-31

views:
  mensapass:
    description: What the canteen pass needs
    fields:
      display_name: [STRING, TEXT]
      student_role_valid_until: [STRING, DATETIME]
    derived:
      pass_valid_until:
        kinds: [STRING, TEXT, DATETIME]
        description: At most seven days ahead
        rule: min(add_days(today(), 7), coalesce(student_role_valid_until, open_ended))
```

| Key | Type | Meaning |
|---|---|---|
| `constants` | mapping | named values every rule may read. YAML types apply: an unquoted `9999-12-31` is a date |
| `views` | mapping | one entry per view type; the key is the `view_type` of the API and of the `person_view` row |
| `views.<name>.description` | string | optional, free text |
| `views.<name>.fields` | mapping | fields a producer writes and the catalogue exposes |
| `views.<name>.derived` | mapping | fields computed at read time |

A stored field is written either in short form, `name: [KIND, …]`, or in long form:

```yaml
      display_name:
        kinds: [STRING, TEXT]
        description: Name as it appears on the pass
```

A derived field is always a mapping and requires `kinds` and `rule`; `description` is
optional.

Startup validation, all of it fatal and all of it performed by `create_app`
(see [startup](#startup)):

* the file exists, parses as YAML, and matches the model;
* no mapping in the document repeats a key — at **every** level, not only view
  names: the fields of one view, the constants, and any other mapping alike;
* every view declares at least one field, stored or derived;
* field names are flat — no dots, and nothing but letters, digits and underscores;
* no name is both a stored and a derived field of the same view;
* every rule parses inside the closed language, with a known function name and the
  right number of arguments;
* every name a rule reads is a declared field, a derived field of the same view, or a
  constant — otherwise no producer would know to write it;
* every argument in a date position of `add_days` or `days_between` provably yields a
  date, following `coalesce`, `min`, `max` and the branches of `if_else` recursively.

A duplicated key is refused while the file is being read, before the model sees it,
because YAML itself would keep only the last of the two — a copy-pasted view block
would otherwise start the service without a word and serve the second definition. The
message names the key and the line:

```text
Duplicate key 'mensapass' in the view configuration: /etc/edutap/views.yaml, line 14.
YAML keeps only the last of two identical keys, so one of the two definitions would be
ignored without a word. Remove or rename one of them.
```

A merge key is not affected. `<<: *anchor` is the one place where the same name may
appear twice — once inherited, once overridden — and YAML gives the explicit value
priority. The check looks at the mapping as it was written, before the merge is
resolved, so inheriting a view's defaults and overriding one of them is allowed while
two literally repeated keys are still refused. Merging is not a way around the check:
every mapping a merge pulls in is checked as well, wherever it is written — bound to
an ordinary key, spelled out at the merge site, listed in a `<<: [*one, *two]`
sequence, or reached through a merge nested in another merge.

```yaml
defaults: &defaults
  description: Inherited description
  fields:
    surname: [STRING, TEXT]

views:
  mensapass:
    <<: *defaults
    description: Explicit description   # wins over the inherited one
```

## Rule functions

The complete language. A rule is one expression built from these calls, field
references, named constants and literals — nothing else parses.

| Function | Arguments | Returns | Behaviour |
|---|---|---|---|
| `today()` | 0 | date | the day the request is evaluated |
| `now()` | 0 | date | the same reference day as `today()`; this language has no time of day |
| `coalesce(a, …)` | 1 or more | any | the first argument that is not `null`, else `null` |
| `if_else(condition, then, otherwise)` | 3 | any | evaluates only the branch it takes |
| `exists(field)` | 1 | boolean | whether the payload carries that key. The argument must be a bare field name; anything else is `false` |
| `is_null(a)` | 1 | boolean | `a` is `null` — including when the key is absent, see below |
| `is_empty(a)` | 1 | boolean | `a` is `null`, `""`, `[]` or `{}` |
| `eq(a, b)` | 2 | boolean | `a == b` |
| `lt(a, b)` | 2 | boolean | `a < b` |
| `gt(a, b)` | 2 | boolean | `a > b` |
| `contains(container, value)` | 2 | boolean | `value` is in `container`; a `null` container is treated as empty |
| `add_days(date, n)` | 2 | date | `date` shifted by `n` days; `null` when `date` is `null`. Argument 0 must be date-like |
| `days_between(a, b)` | 2 | number | whole days from `b` to `a`; `null` when either is `null`. Both arguments must be date-like |
| `min(a, …)` | 1 or more | any | smallest argument, ignoring `null`; `null` when all are `null` |
| `max(a, …)` | 1 or more | any | largest argument, ignoring `null`; `null` when all are `null` |
| `first(a)` | 1 | any | first element of an array; `null` when it is empty or `null` |
| `join(separator, values)` | 2 | string | the values joined with `separator`; a `null` array joins to `""` |

The conditional is named `if_else` and not `if` because `if` is a Python keyword: the
parser underneath is `ast.parse`, so a rule written as `if(…)` could not be parsed at
all.

`exists` and `is_null` are different questions. In JSONB an absent key and a key
holding `null` are distinct states — but only `exists` can tell them apart. Reading a
field yields `null` in both cases, so `is_null(x)` is `true` for a key that is missing
just as much as for a key written as `null`. When the question is *did the producer
write this field at all*, the answer is `exists(x)`; `is_null(x)` answers *is there a
value here*, which is the weaker and more usual question.

Fields declaring `DATETIME` are turned into real date objects before a rule runs, so
arithmetic and comparison happen on dates rather than on strings. Only the result is
serialised back to an ISO string.

Anything outside this table is rejected: an unknown function name, a keyword
argument, an attribute access, an operator, a comprehension, a lambda. Adding a
function is a code change with a review.

## Field kinds

What a field is *good for*, not what it holds. `edutap.pass_builder` validates
mapping rules against these when a template version is published.

| Kind | Meaning |
|---|---|
| `STRING` | usable as a plain string value |
| `TEXT` | may be shown as text on the pass |
| `DATETIME` | holds an ISO date or timestamp; parsed into a real date before rules run |
| `LINK` | may be used as a hyperlink target |
| `NFC` | may go into an NFC payload |
| `BARCODE` | may go into a barcode payload |
| `IMAGE` | a reference to an image; never the bytes themselves |

## Vocabulary

Two enumerations. A consumer may either copy their values or import them, and which
of the two is right follows from whether it already depends on this package:

* A consumer that must **not** depend on the data provider — `edutap.pass_builder`,
  say — **copies** the values. Importing them would point its dependency at the
  service it consumes.
* A consumer that already depends on this package **imports** them, from the package
  root or from the submodule; both are part of the public API:

  ```python
  from edutap.data_provider import PassLifecycleState, WalletType
  ```

`WalletType`: `GOOGLE_ST`, `GOOGLE_ACCESS`, `APPLE_VAS`, `APPLE_ACCESS`,
`APPLE_IDENTITY`, `SAMSUNG_ST`, `SAMSUNG_ACCESS`.

`PassLifecycleState`: `NEW`, `INSTALL_PENDING`, `UPDATE_PENDING`, `DELETE_PENDING`,
`ACTIVE`, `INACTIVE`.

Both are stored in text columns rather than native enums, so a new wallet provider
does not force a migration in every installation. The price is that the database does
not enforce the values.

## Database tables

The package owns two tables and reads both. It never creates them: the DDL is
rendered and applied by `edutap.db_definitions`, which this package announces its
metadata to through the `edutap.db_definitions` entry point. Constraint and index
names follow the shared naming convention, and the Alembic version table is
`alembic_version_data_provider`.

```console
$ edutap-dbdef create --packages edutap.data_provider --out schema.sql
```

### `person_view`

One view of one person: the payload a consumer of this view type may see.

| Column | Type | Meaning |
|---|---|---|
| `person_uid` | `VARCHAR(64) COLLATE "C"`, primary key part | person identifier, uniquely determinable by the university: ePPN, UUID or hash. Never interpreted here. Byte collation, so comparison and index order do not depend on a locale |
| `view_type` | `VARCHAR(64) COLLATE "C"`, primary key part | `full_view` or a speaking slice such as `mensapass` |
| `data` | `JSONB`, not null | the payload |
| `updated_at` | `TIMESTAMPTZ`, not null | maintained by the database |

The primary key is **composite**, `(person_uid, view_type)` — exactly one row per
person and view type. Index `ix_person_view_view_type` on `view_type`, so a SQL
reader can take all rows of one view without a full scan.

Payload rules, binding for producers:

* flat: no dotted keys, no nested objects;
* standard-native names from eduPerson, SCHAC and dfnEduPerson, without a renaming
  layer;
* arrays where an attribute is genuinely multi-valued, such as `mail` or
  `eduperson_affiliation`;
* a photo is a flat reference, never bytes and never an object.

### `pass_state`

One issued pass and where it stands in its life. One row per issued pass instance,
not per combination.

| Column | Type | Meaning |
|---|---|---|
| `pass_id` | `VARCHAR(255)`, primary key | the provider's pass identifier. Not a UUID column: usually a UUID, but Google Wallet object identifiers carry a prefix and suffix |
| `person_uid` | `VARCHAR(64) COLLATE "C"`, not null | as above. **No foreign key**: a pass exists whether or not a view row currently does |
| `wallet_type` | `VARCHAR(32)`, not null | a `WalletType` value |
| `state` | `VARCHAR(32)`, not null | a `PassLifecycleState` value. Stored and delivered, never validated here |
| `pass_template` | `VARCHAR(64)`, not null | speaking template key, matching `Template.key` in `edutap.pass_builder` |
| `pass_template_variant` | `VARCHAR(64)`, nullable | variant key; empty means the default variant, which `pass_builder` models as `is_default` |
| `created_at` | `TIMESTAMPTZ`, not null | issued at |
| `updated_at` | `TIMESTAMPTZ`, not null | last changed |

Indexes: `ix_pass_state_person_uid` on `person_uid`, and
`ix_pass_state_person_template_wallet` on `(person_uid, pass_template, wallet_type)`
— the question the readers actually ask, *which passes does this person have?*

The HTTP API does not expose `pass_state`. It is read through the
[SQL profile](how-to.md#let-a-sql-consumer-read-the-tables-directly).

## Python entry points

| Object | Purpose |
|---|---|
| `edutap.data_provider.api.app:create_app` | the FastAPI application factory; run it with `uvicorn … --factory` |
| `edutap.data_provider.models.dbdef:definition` | the `SchemaDefinition` announced to `edutap.db_definitions` |
| `edutap.data_provider` | the package root re-exports `WalletType`, `PassLifecycleState`, `FieldKind` and `__version__` |
| `edutap.data_provider.vocabulary` | where those three enumerations are defined |
