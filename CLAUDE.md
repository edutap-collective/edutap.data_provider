# CLAUDE.md — edutap.data_provider

Repository-specific rules. They take precedence over the global defaults.

## Language

**English only.** This repository belongs to eduTAP proper, not to any single
institution: README, changelog, documentation, docstrings, code comments, commit
messages, pull request titles and bodies, and replies to review comments.

The language follows the repository, not the conversation. A discussion held in
German still produces English artefacts here.

## What this service is

A read-only service that resolves requested fields into a data-minimising projection:
`GET /catalogue` and `POST /lookup`.

## Guard rails

**This service never writes a row and never runs DDL.** No `INSERT`, no `UPDATE`, no
`DELETE`, no `CREATE TABLE`. Its database account needs `SELECT` alone — a property
an auditor can check in the database rather than a promise in a review. Anything that
would need a write belongs in a producer, not here.

**The schema is owned here, applied elsewhere.** This package brings the model and
announces it through the `edutap.db_definitions` entry point; `db_definitions`
renders the SQL and a privileged role applies it.

**The HTTP API is the mandatory surface, the SQL profile is optional.** Cloud
implementations of the same contract have no database to share. Never make SQL a
precondition for anything a consumer needs.

**Minimisation is a property of what a producer writes**, not something a reader can
repair. The API can promise it because it answers only what the catalogue declares;
raw SQL cannot.

## Sources and confidentiality

**No vendor internals — from any vendor, not just the ones currently in play.**
Neither in files nor in commit messages.

The standard is academic: a statement counts as reliable only where it can be
evidenced from public information, with a link. Everything else was obtained either
by our own testing or through insider knowledge, and the three are not
interchangeable:

* **Documented** — public source, linked. May be written as fact.
* **Measured** — established by our own tests. May be written down, but always marked
  as such, because it describes what a platform did on the day we looked, not what it
  guarantees. It can change with the next release, without notice and without an
  entry in any changelog.
* **Insider knowledge** — is not written down at all.

What a platform's behaviour *means for us* stays documentable even where the
mechanism does not: "the platform enforces a deadline, it is self-healing, it is
outside our control" carries the design consequence without disclosing anything.

Contract and regulatory material is wanted and citable: eduPersonAssurance, GÉANT and
eduGAIN terms, published wallet programme obligations.

## Working practice

Branch first, never commit on `main`. Push only when asked. Lint and tests green
before opening a pull request.

Design records under `docs/superpowers/` record a decision at a point in time — do
not rewrite them to match a later state; write a new one.
