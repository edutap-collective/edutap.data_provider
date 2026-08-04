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

## Why copying the vocabulary is recommended, and when importing is right

`WalletType` and `PassLifecycleState` exist here as `StrEnum`s. They are exported
from the package root as well as from `edutap.data_provider.vocabulary`, so a
consumer can import them — and the recommendation is nevertheless that most
consumers **copy** the values instead.

The reason is a dependency direction. `edutap.pass_builder` consumes this service; if
it imported the vocabulary from here, its dependency would point at the thing it
consumes, and a version bump on the provider would ripple into every consumer's
resolution. A dozen short string constants are not worth that edge in the
dependency graph. The same rule — and the same reason — applies to the naming convention this
package copies from `edutap.db_definitions`, and to keeping `edutap.db_definitions`
itself a development dependency that is never deployed.

That reasoning only bites where the dependency would be new. A consumer that already
depends on `edutap.data_provider` — this repository's own tests, a deployment's glue
code, a producer written against this package — has nothing left to protect by
copying, and for it a copy is simply a second definition that can drift. So the
import is deliberately available and supported:

```python
from edutap.data_provider import PassLifecycleState, WalletType
```

Read the recommendation as being about the dependency, not about the import
statement: copy when importing would create a dependency you do not want, import when
the dependency is already there.

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

## What leaves the process, and what does not

The service exists so that a consumer sees only the fields it needs. An error
tracker is a machine that copies the state around a failure somewhere else, so
pointing one at this service is a decision about personal data, not a piece of
operations plumbing.

There are two such machines here, and the decision is the same for both: an error
tracker reached by a Sentry DSN, and an OpenTelemetry collector reached by an OTLP
endpoint. They are configured independently and neither implies the other, but
nothing below is true of only one of them — in particular, the keyed pseudonym that
stands in for a person travels on both, as a tag on an event and as an attribute on
a span.

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

What reaches either backend is therefore: the exception and its stack, the view
type, the name of a field, and — only if a salt is configured — a keyed pseudonym of
the person. What never reaches them: the API token, the database password, the
`person_uid`, the client's IP address, and any stored value. An event also carries
the request URL and method, the surviving headers, the environment name and the
list of installed modules; nothing there is personal, but the list above is what was
decided, not an exhaustive inventory of an envelope.

The pseudonym is an HMAC under a per-installation salt, truncated to 12 hex
characters. An unkeyed hash would not do: a `person_uid` comes from a directory, so
anyone able to read the error tracker could hash the directory and undo it. Rotating
the salt renames every pseudonym, which is intended — a pseudonym should not follow a
person for ever. No salt, or an empty one, means no pseudonym at all, rather than a
digest under an empty key, which would be the reversible construction again.

### The named limitation: the text of an exception message

The one remaining channel is the text of an exception message. It reaches both
backends: Bugsink is built to show it, and the OTLP instrumentation copies it into
the span as `exception.message` and `exception.stacktrace`. Nothing scrubs it on
either path, and that is a deliberate, accepted boundary rather than an oversight —
so it is written down here, where the person deciding whether to point a collector
at this service will read it.

Accepting it imposes a discipline on both kinds of message that can travel.

The messages this service writes name a field and a view and never a value, and the
one message that did — a rule failing on a stored value — no longer has a route out
of the process at all.

Messages this service does *not* write are the harder half, and are the reason this
limitation is named rather than assumed away. A dependency phrases its own errors,
and one of them quoted a person: SQLAlchemy appends the bound parameters of a
failing statement to every database error it raises, and the first bound parameter
of the only statement this service issues is the `person_uid`. A dropped pool
connection was enough. The engine is now built with `hide_parameters=True`, which
closes that at the source — the statement still travels, the values bound into it do
not — and the same flag keeps the parameters out of the engine's own SQL logging.

A control on the channel itself was considered and rejected as disproportionate.
logfire's scrubber, the only supported hook on the OTLP path, treats
`exception.message`, `exception.type` and `exception.stacktrace` as safe keys: no
callback and no pattern reaches them. Filtering them would mean taking over the
export path — building the OTLP exporter and its batch processor by hand, inside a
wrapping exporter — which replaces the one piece of this wiring that was measured
most carefully, the bounded shutdown that keeps a SIGTERM from becoming a SIGKILL
against an unreachable collector. It would also buy less than it appears to: the
identical channel stays open on the Sentry side, where an exception's text is the
entire point of the product, so the result would be a trace that hides what the
error tracker shows. Closing the one measured leak at its source, and naming the
boundary here, is the better trade.

What this means operationally: **treat the OTLP collector as being as sensitive as
the error tracker.** Both may receive an exception message written by a library,
under a failure mode nobody has seen yet. Point them at systems the university
operates, not at a third-party SaaS endpoint.
