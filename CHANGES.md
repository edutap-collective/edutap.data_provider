# Changelog

## 0.1.0 (unreleased)

- Initial release: `GET /catalogue` and `POST /lookup` over configured views, with
  read-time derivation from a closed rule language.
- Two tables, `person_view` and `pass_state`, announced to `edutap.db_definitions`
  through an entry point. The service creates no table and writes no row.
- Bearer authentication; the service's own errors as `application/problem+json`.
- Docker test environment, and documentation following Diátaxis.
- Optional error reporting to Bugsink and OTLP export of traces, both off unless
  configured. No credential, no `person_uid`, no client address and no stored value
  leaves the process; a keyed pseudonym stands in for a person. The one accepted
  exception is the text of an exception message, which reaches both backends
  unfiltered — named, with its consequences, under "What leaves the process, and
  what does not" in `docs/explanation.md`.
