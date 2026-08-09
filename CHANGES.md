# Changelog

## 0.1.0 (unreleased)

- Initial release: `GET /catalogue` and `POST /lookup` over configured views, with
  read-time derivation from a closed rule language.
- Three tables — `person_view`, `pass_state` and `pass_instance` — announced to
  `edutap.db_definitions` through an entry point. All three declare the schema
  `public` explicitly, rather than inheriting it from `search_path`. The service
  creates no table and writes no row.
- `person_view` carries a `photo` reference (JSONB, source deliberately open).
- The pass lifecycle is two axes: `IssuanceState` is what the issuer did or
  wants, entirely under its own control; `HolderState` is derived from
  `pass_instance` and never set directly. `pass_state` carries a `version`
  counter, the `last_event_at` watermark and `provider_raw`. `pass_instance`
  holds zero to n exemplars of a pass at the holder — a device registration or
  provisioned credential at Apple, the save into the account at Google.
- Bearer authentication; the service's own errors as `application/problem+json`.
- Docker test environment, and documentation following Diátaxis.
- Optional error reporting to Bugsink and OTLP export of traces, both off unless
  configured. No credential, no `person_uid`, no client address and no stored value
  leaves the process; a keyed pseudonym stands in for a person. The one accepted
  exception is the text of an exception message, which reaches both backends
  unfiltered — named, with its consequences, under "What leaves the process, and
  what does not" in `docs/explanation.md`.
