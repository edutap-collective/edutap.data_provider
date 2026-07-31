# Explanation

Why the service is shaped the way it is. The decisions below come from the design
record in `docs/superpowers/specs/2026-07-30-data-provider-design.md`; this page
argues them rather than restating them.

## The starting principle: the data stays at the university

eduTAP issues wallet passes, and a pass issuer is by construction a party the
university does not fully control. The principle that follows is that person data
stays at the university and never accumulates at the issuer. Two consequences run
through everything else here:

* every installation needs its own statement about which passes exist for which
  person — the data provider plus the internal databases is the only thing every
  eduTAP stack has, so that statement lives here;
* what a consumer receives is a *projection*, cut to purpose, rather than a person
  record it may keep.

## Why the service is read-only, and who writes instead

The service never writes a row. It issues `SELECT` and nothing else — no `INSERT`,
no `UPDATE`, no `DELETE`, no `CREATE TABLE`. Its database account needs `SELECT`
alone, which is a property an auditor can check in the database rather than a promise
in a code review.

Three parties write instead, all outside this process:

* **`edutap.db_definitions`** applies the schema, with a privileged user, from DDL
  rendered out of this package's own metadata. Nothing that runs in production
  carries the right to change a table.
* **A producer** fills `person_view`. At LMU that is the VZD webhook, from directory
  events. Which fields it writes follows from the view configuration; how it obtains
  them is its own business, and deliberately not this package's.
* **The worker** writes `pass_state` from Kafka events. Callback handlers and
  webhooks publish events, they never touch the database.

The gain is not tidiness. A read-only service cannot corrupt the record it serves,
its failure modes are limited to answering wrongly rather than storing wrongly, and
it can be scaled or restarted without a thought about write consistency.

## Why the API is mandatory and the SQL profile is optional

`edutap.data_provider` is first a contract and then an implementation. HEIDI Local
and helixpass implement the same contract as cloud products; the package here is the
generic reference implementation.

That is what makes the two surfaces unequal. The HTTP API — `GET /catalogue` and
`POST /lookup` — must exist in every implementation, including one that runs in a
cloud and has no database it could share. Making SQL mandatory would exclude those
implementations outright.

The SQL profile exists because forbidding it would break the one consumer that
already works: HEIDI Local reads a table directly and maps it through a `field_map`
in its deployment configuration. Documenting the profile as *raw rows, bring your own
post-processing* costs nothing and keeps that consumer running unchanged.

The asymmetry is honest about what each surface can promise. The API can guarantee
data minimisation, because it answers only what the catalogue declares. SQL cannot:
the row is the row. That is why an external consumer belongs on the API, and why
minimisation is ultimately a property of what a producer writes into a dedicated
view — not something a reader can repair afterwards.

## Why derivation runs at read time

A field like `pass_valid_until` could be computed by the producer and stored. It is
not, for four reasons that all point the same way:

* **The rule lives once.** A corrected rule takes effect immediately, for every
  person, without rewriting a single row. Stored derivation would need a backfill
  every time a policy changes, and a rolling one at that.
* **The producer stays simple.** It writes what the directory says. It does not need
  to know what a pass is, how long one may be valid, or which template carries which
  role.
* **The service stays read-only.** Storing a derived value would mean writing, and
  writing here would put the service back in the position the previous section
  removed it from.
* **Time-dependent values are correct by construction.** `add_days(today(), 7)`
  answers relative to the moment of the request. A stored value would be stale the
  next day and would need a scheduled job to keep it fresh.

The price is paid honestly: a SQL reader does **not** see derived fields, because
they exist only inside a response. That is the same trade-off as HEIDI's `field_map`
— post-processing on the reading side — and it is why the SQL profile is documented
as raw.

## Why the rule language is closed

The rules live in a deployment's YAML file, which means they are edited by people who
are not reviewing this package. A closed set of named functions over field
references, literals and constants — no operators, no attribute access, no
user-defined syntax, no `eval` — buys three things:

* **A startup type check.** Because every function declares what it returns and which
  arguments must be dates, applying `add_days` to a field that does not declare
  `DATETIME` is a configuration error that stops the process. The alternative is a
  silent string comparison in which `2026-12-01` sorts before `2026-2-01` and a pass
  quietly expires nine months early.
* **Rules that can be read at a glance.** A reviewer sees a fallback, a minimum and
  an offset, and knows the whole meaning.
* **A boundary that has to be crossed deliberately.** Adding a function is a code
  change with a review, precisely so that no small programming language grows inside
  a deployment YAML.

If a real case ever exceeds the set, the documented escape hatch is a safe Python
subset via RestrictedPython. It is not part of version 1, because it would cost
exactly what makes the closed set valuable.

Open-endedness follows the same reasoning from the other direction. At LMU an
unlimited role is written as `9999-12-31`. Treating that as a special case in the
package would make the package wrong for a site that uses a different sentinel, so it
is a named constant in the configuration. Written once, read by name, and visibly not
a real date.

## Why field names are standard-native and flat

The payload uses the names the higher-education world already uses — eduPerson,
SCHAC, dfnEduPerson — and there is no renaming layer anywhere in this package.
An invented vocabulary would have to be documented, learned and translated at every
boundary; the standard names are already understood by the directory, the producer
and the consumers.

Flat means no dotted keys and no nested objects — the configuration refuses a field
name containing a dot. A flat payload keeps the projection a pure lookup, keeps rule
references unambiguous, and keeps the JSONB queryable for a SQL reader without path
expressions. Multi-valued attributes stay arrays, which is LDAP-native and loses
nothing.

The one thing this costs is that a producer with genuinely 1:n structures — study
programmes, employments, organisational units — must decide how to flatten them.
That decision belongs to the producer: the catalogue simply declares whatever it
writes.

## Why the vocabulary is copied rather than imported

`WalletType` and `PassLifecycleState` exist here as `StrEnum`s, and consumers are
asked to **copy** the values instead of importing this package.

Importing would invert a dependency. `edutap.pass_builder` consumes this service; if
it imported the vocabulary from here, its dependency would point at the thing it
consumes, and a version bump on the provider would ripple into every consumer's
resolution. The same rule — and the same reason — applies to the naming convention
this package copies from `edutap.db_definitions`, and to keeping
`edutap.db_definitions` itself a development dependency that is never deployed.

The values are stored in text columns rather than native enums for a related reason
at the database level: a new wallet provider must not force a migration in every
installation. The database therefore does not enforce the vocabulary, which is a
deliberate and named trade-off, not an oversight.

## Why the view type is not an entitlement

A `view_type` says *what kind of view onto the directory data* a row is: `full_view`
is the complete record, `mensapass` is what one pass template needs. It exists for
data minimisation towards a reader that may sit outside the university.

It is emphatically **not** a statement that a person is entitled to a pass.
Authorisation happens earlier, where the pass is requested; hanging it on the view
row would be far too late, and would quietly turn a data-minimisation mechanism into
an access-control one that nothing tests.
