# edutap.data_provider

Person data provider for eduTAP. It resolves the fields a caller asks for into a
projection for exactly one person, so that pass-issuing services never receive more
personal data than they need.

The package is **first a contract, then an implementation**: HEIDI Local and
helixpass implement the same contract as cloud products, and this is the generic
reference implementation.

## The two contract surfaces

**HTTP API — mandatory.** Bearer authentication; the service's own errors as
`application/problem+json`.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/catalogue` | `?view_type=…` → the declared field list of one view: `key`, `kinds`, `derived`, `description` |
| POST | `/lookup` | `{person_uid, view_type, fields}` → a map with exactly the requested fields |
| GET | `/healthz` | liveness, without authentication |

**SQL profile — optional.** An implementation whose consumers sit in the same
database may let them read `person_view` and `pass_state` directly. Those tables
deliver raw rows: no projection, no derivation. A direct reader brings its own
post-processing — HEIDI Local's `field_map` is exactly that.

## How it works

* **Views, not person records.** A `view_type` is a slice of the directory data cut
  for one purpose: `full_view` is the complete record, `mensapass` is what one pass
  template needs. It is a data-minimisation device, not an entitlement statement.
* **The payload is flat.** No dotted keys, no nested objects — a field name with a
  dot in it is refused at startup. Names are standard-native (eduPerson, SCHAC,
  dfnEduPerson) and multi-valued attributes are arrays.
* **Kinds, not types.** `STRING`, `TEXT`, `DATETIME`, `LINK`, `NFC`, `BARCODE`,
  `IMAGE` say what a field is good for. `edutap.pass_builder` checks them when a
  template version is published.
* **Derived fields are computed at read time** from a closed rule language — a fixed
  set of named functions over field references, constants and literals, validated at
  startup. They stand in the catalogue as equals; no row stores them.
* **Read-only, without exception.** The service issues `SELECT` and nothing else.
  `edutap.db_definitions` applies the schema with a privileged database user, and a
  deployment-specific producer fills `person_view` — at LMU the VZD webhook, from
  directory events, while the worker writes `pass_state` from Kafka events.

## Install and run

```console
$ make venv                      # .venv with the dev extra
$ cp .env.example .env           # then edit it
$ make test-local                # unit tests, no database
$ make run                       # uvicorn against the compose environment
```

Or with the Docker test environment:

```console
$ docker compose up -d db
$ .venv/bin/edutap-dbdef create --packages edutap.data_provider --out schema.sql
$ docker compose exec -T db psql -U data_provider -d data_provider < schema.sql
$ docker compose up -d app
```

Configuration is `EDUTAP_DATA_PROVIDER_DATABASE_URL`, `..._CONFIG_PATH`,
`..._API_TOKEN` and `..._ECHO_SQL`; `views.example.yaml` is a complete working view
configuration.

## Consumers

`edutap.pass_builder` (through its data provider client) and, later, the
`edutap.pass_builder_manager`. HEIDI Local reads the tables through the SQL profile.

## Documentation

`docs/` — a walked-through tutorial, how-to guides, the complete reference and the
reasoning behind the design. Build it with
`.venv/bin/python -m sphinx -E -W docs docs/_build/html` after
`uv pip install -e ".[docs]"`.

The design record is `docs/superpowers/specs/2026-07-30-data-provider-design.md`.
