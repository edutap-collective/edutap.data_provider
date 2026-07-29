# edutap.data_provider

Person data provider for eduTAP. It resolves the fields a caller asks for into a
projection for exactly one person, so that pass-issuing services never receive more
personal data than they need.

**Status: planned.** The design is agreed; implementation has not started.

## Planned surface

| Endpoint | Purpose |
| --- | --- |
| `POST /lookup` | `{person_uid, pass_type, fields}` → map of the requested fields |
| `GET /catalogue` | the declared field catalogue for one `pass_type` (`key`, `value_type`, `label`, `required`, `description`) |

Bearer authentication; errors as `application/problem+json`.

## Design in short

* A **field router** distributes every requested field to the source that owns it
  and merges the results into one projection.
* Sources sit behind **pluggable adapters**. The first adapter reads a PostgreSQL
  view cache keyed by `(person_uid, pass_type)` whose payload uses flat, dotted
  keys (`person.name`), so a lookup is a pure projection.
* The field catalogue is declared configuration (YAML via pydantic-settings), one
  field set per `pass_type`.
* `person_uid` is a SAML-scoped identifier (eduPersonUniqueId).
* **Read-only.** This package owns the generic data model of the view table, but
  applying migrations is the job of `edutap.db_definitions`, which runs with a
  privileged database user. Filling the view table is the job of a
  deployment-specific producer.

## Consumers

`edutap.pass_builder` (through its data provider client) and, later, the
`edutap.pass_builder_manager`.

The full design record currently lives in the LMU deployment repository
(`lmu_edutap_dev_setup/docs/superpowers/specs/2026-07-24-data-provider-design.md`)
and moves here with the first implementation commit.
