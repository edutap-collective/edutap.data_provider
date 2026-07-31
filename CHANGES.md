# Changelog

## 0.1.0 (unreleased)

- Initial release: `GET /catalogue` and `POST /lookup` over configured views, with
  read-time derivation from a closed rule language.
- Two tables, `person_view` and `pass_state`, announced to `edutap.db_definitions`
  through an entry point. The service creates no table and writes no row.
- Bearer authentication; the service's own errors as `application/problem+json`.
- Docker test environment, and documentation following Diátaxis.
