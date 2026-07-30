# Design: `edutap.data_provider` — person views and pass lifecycle

Date: 2026-07-30
Status: approved

## Goal

`edutap.data_provider` is **first a contract, then an implementation**. The contract
describes how a consumer inside a university reaches person data and pass states.
HEIDI Local and helixpass are alternative implementations of that same contract for
their cloud-based products; the package in this repository is the generic reference
implementation.

Two things follow from the eduTAP principle that **the data stays at the university,
never at the pass issuer**:

* Every installation needs its own statement about which passes are issued, for which
  person, pass type and wallet provider. That statement lives here, because a data
  provider plus the internal databases is the only thing every eduTAP stack has.
* The service is **read-only, without exception**. It never writes a row.

Non-goals: any write path, interpreting or validating lifecycle transitions, search
endpoints, person listings, and anything wallet-specific. The service stores nothing
and judges nothing — it declares, reads, derives and delivers.

## Starting point

The July 2026 decision record (`lmu_edutap_dev_setup`,
`docs/superpowers/specs/2026-07-24-data-provider-design.md`) established the first
twelve decisions. This document supersedes it: the decisions are carried forward
where they still hold and corrected where later work showed them wrong.

What exists today and shapes this design:

| Component | Relevance |
|---|---|
| `lmu_edutap_full_view` | owns `heidi_full_view` (person_uid PK, `data` JSONB, `photo` JSONB) and `pass_state` (passid UUID PK, person_uid FK, preset_id, preset_title, state, wallet_type). Both concepts move here; the package itself is retired, not rebuilt |
| HEIDI Local | reads `heidi_full_view` **directly by SQL** (`table:`, `id_column:`, `json_columns:`), and maps it to its own flat model through a `field_map` in deployment config |
| `edutap.pass_builder` | consumes this service. Has `Template.key` and `TemplateVariant.key` with `is_default` per template and wallet type — the vocabulary this design reuses |
| `edutap.db_definitions` | defines how a package announces its tables. This is the first package built against that contract |
| `lmu_edutap_data_vzd_webhook` | the LMU producer: eDirectory events over Kafka, writes person view rows |
| `lmu_edutap_worker` | the only component that writes the lifecycle table; it will execute the spooler code that `edutap.webhook_heidi` provides |

## The contract has two surfaces

**HTTP API — mandatory.** `GET /catalogue` and `POST /lookup`. The field catalogue,
the field projection and the derivation rules live here. Every implementation must
offer this, including one that runs in a cloud and has no database to share.

**SQL profile — optional.** An implementation whose consumers sit in the same
database may let them read the tables directly. Those tables deliver **raw rows**: no
projection, no derivation. A direct reader brings its own post-processing — HEIDI's
`field_map` is exactly that, and it keeps working unchanged.

The two surfaces are deliberately unequal. Making SQL mandatory would exclude cloud
implementations; making it forbidden would break the one consumer that exists today.

## Who writes

Nobody in this service. Two components outside it write, both asynchronously:

* the **worker** consumes Kafka and writes `pass_state` — the callback handlers and
  webhooks publish events to Kafka, they never touch the database;
* the **VZD webhook** writes `person_view` from directory events.

## Data model

### `person_view`

| Column | Type | Meaning |
|---|---|---|
| `person_uid` | `String(64, collation="C")`, PK part | person identifier, uniquely determinable by the university: ePPN, UUID or hash. The service never interprets it. Byte collation, carried over from `full_view`, so comparison and index order do not depend on a locale |
| `view_type` | `String(64, collation="C")`, PK part | `full_view`, or a speaking slice such as `mensapass`, `esc` |
| `data` | `JSONB` | the payload |
| `updated_at` | `timestamptz` | maintained by the database |

Primary key `(person_uid, view_type)` — exactly one view per person and type. An
index on `view_type` so a SQL reader can take "all rows of `full_view`" without a
full scan.

A `view_type` describes **what kind of database view onto the directory data** a row
is. `full_view` is the complete record; a dedicated view carries what one pass
template needs. The row exists for data minimisation towards a reader that may sit
outside the university — it is **not** an entitlement statement. Authorisation
happens earlier, and hanging it on the view row would be too late.

**Payload rules**, binding for producers:

* Flat. No dotted keys, no nested objects.
* Standard-native names from the schemas the higher-education world already
  uses — eduPerson, SCHAC, dfnEduPerson — because they are better understood than
  any mapping we could invent. No renaming layer anywhere.
* Arrays are allowed where an attribute is genuinely multi-valued (`mail`,
  `eduperson_affiliation`). That is LDAP-native and loses nothing.
* A photo is a **flat reference**, never bytes and never an object. Delivery of the
  image is the business of `edutap.image_service`. A view that does not need a photo
  never carries the field.

### `pass_state`

| Column | Type | Meaning |
|---|---|---|
| `pass_id` | `String(255)`, PK | the provider's unique pass identifier. **Not a UUID column**: usually a UUID, but Google Wallet object identifiers carry a prefix and suffix (`issuerId.suffix`) |
| `person_uid` | `String(64)`, indexed | as above, **without** a foreign key |
| `wallet_type` | `String(32)` | `GOOGLE_ST`, `GOOGLE_ACCESS`, `APPLE_VAS`, `APPLE_ACCESS`, `APPLE_IDENTITY`, … |
| `state` | `String(32)` | `NEW`, `INSTALL_PENDING`, `UPDATE_PENDING`, `DELETE_PENDING`, `ACTIVE`, `INACTIVE` |
| `pass_template` | `String(64)` | speaking template key, matching `Template.key` in `edutap.pass_builder` |
| `pass_template_variant` | `String(64)`, nullable | variant key, matching `TemplateVariant.key`. Empty means the default variant, which `pass_builder` already models as `is_default` per template and wallet type |
| `created_at` / `updated_at` | `timestamptz` | issued at / last changed |

Index on `(person_uid, pass_template, wallet_type)` — that is the question the
readers ask (`lmu_edutap_backend`, `lmu_edutap_admin_backend`,
`edutap.apple_wallet_vas_web_service`, the scheduled tasks, and possibly the data
provider itself): "which passes does this person have?"

One row per **issued pass instance**, not per combination. The state belongs to the
instance: a `DELETE_PENDING` on the old pass and an `ACTIVE` on its replacement must
be representable at the same time, otherwise the webhook consumer loses information
it just received.

**No foreign key to the person.** Today `pass_state.person_uid` references
`heidi_full_view.person_uid`, which works because that is the whole primary key
there. With a composite key it cannot, and that is honest rather than a loss: an
issued pass exists whether or not a view row currently does, and it must not
disappear when a view is deleted.

**`preset_id` and `preset_title` are dropped without replacement.** They were HEIDI's
words for template and variant; the two fields above say it in eduTAP's own terms.

**Vocabulary as text, not as a native enum.** `wallet_type` and `state` get a
`StrEnum` in the Python model and a text column in the database, so a new wallet
provider does not force a migration in every installation. This deviates from
`pass_builder`, which uses a native enum today; the price is that the database does
not enforce the values.

**Where the vocabulary lives.** It exists three times today (`pass_builder` native
enum, `edutap.heidi_api` Pydantic enums, `full_view` literals). It is defined here,
and consumers **copy** it rather than importing it — the same rule
`edutap.db_definitions` uses for its naming convention, and for the same reason: the
alternative would point `pass_builder`'s dependency at the service it consumes.

## View definitions and derivation rules

One YAML file, its path from `EDUTAP_DATA_PROVIDER_CONFIG`, read through
pydantic-settings. The shape follows HEIDI Local's connector config — which was
itself built from eduTAP ideas — but carries any number of views instead of exactly
one.

```yaml
constants:
  open_ended: 9999-12-31

views:
  full_view:
    description: Complete person record as the producer writes it
    fields:
      eduperson_principal_name: [STRING, TEXT, NFC]
      given_name:               [STRING, TEXT]
      surname:                  [STRING, TEXT]
      mail:                     [STRING, TEXT, LINK]
      eduperson_affiliation:    [STRING, TEXT]
      lmu_matriculation_number: [STRING, TEXT, BARCODE]

  mensapass:
    description: What the canteen pass needs
    fields:
      eduperson_principal_name: [STRING, TEXT, NFC]
      display_name:             [STRING, TEXT]
    derived:
      pass_valid_until:
        kinds: [STRING, TEXT, DATETIME]
        rule: >
          min(add_days(today(), 7),
              coalesce(student_role_valid_until, open_ended),
              coalesce(employee_role_valid_until, open_ended))
```

**Kinds, not types.** `STRING`, `TEXT`, `DATETIME`, `LINK`, `NFC`, `BARCODE`, `IMAGE`
say what a field is *good for*, not what it holds. `pass_builder` validates mapping
rules against them when a template version is published: putting a field into an NFC
payload is only allowed if the field declares `NFC`. This replaces the `value_type`
of the July catalogue.

**Derived fields stand in the catalogue as equals.** A consumer sees
`pass_valid_until` and does not need to know it comes into being at read time.

**Where a rule's inputs come from: the same view row.** The `mensapass` row therefore
contains `student_role_valid_until` and `employee_role_valid_until` even though the
catalogue does not list them — they are raw material, not output. The producer's
contract follows from this without extra bookkeeping: **it must write exactly those
fields that appear anywhere in the view's configuration**, declared or referenced.

A row may hold fields the configuration never mentions. They are tolerated and
**invisible over the API** — the catalogue is the exposed surface, and `/lookup`
answers only what the catalogue declares. A SQL reader sees them, which is one more
reason the SQL profile is documented as raw. Data minimisation towards an external
reader is therefore a property of what the producer writes into a dedicated view,
not something the API can repair after the fact.

**Derivation runs at read time**, in this service. The rules live once, in the view
configuration; a corrected rule takes effect immediately for every person without
rewriting a single row, the producer stays simple, and the service stays read-only.
A SQL reader therefore does **not** see derived fields — it reads raw rows and brings
its own post-processing, which is what HEIDI's `field_map` already is.

### The rule language

A closed set of named functions over field references, literals and constants. No
user-defined expressions.

| Group | Functions |
|---|---|
| Values | field reference, literal, named constant, `today()`, `now()` |
| Selection | `if(condition, then, else)`, `coalesce(a, b, …)` |
| Conditions | `exists(a)`, `is_null(a)`, `is_empty(a)`, `eq(a, b)`, `lt(a, b)`, `gt(a, b)`, `contains(array, value)` |
| Dates | `add_days(date, n)`, `days_between(a, b)`, `min(…)`, `max(…)` |
| Arrays | `first(a)`, `join(separator, a)` |

`exists` and `is_null` are different questions: in JSONB an absent key and a key with
a null value are distinct states. A student simply has no
`employee_role_valid_until`. Using presence as a proxy for role membership is
fragile, though — the robust form is `contains(eduperson_affiliation, 'employee')`,
and the documentation says so.

**Real date objects, driven by the declared kinds.** JSONB holds an ISO string. A
field declaring `DATETIME` is parsed into a real `date`/`datetime` before evaluation,
arithmetic happens on that, and only the output is serialised again. This makes a
**startup type check** possible: `add_days` on a field that does not declare
`DATETIME` is a configuration error that prevents the service from starting — rather
than a silent string comparison in which `2026-12-01` sorts before `2026-2-01`.

**Open-endedness is a value, not a special case.** At LMU an unlimited role carries
`9999-12-31`. It belongs in the configuration as a named constant, not in the
package: another site may use a different sentinel. Written once, every rule reads it
by name, and a reader sees immediately that it is not a real date.

Adding a function is a code change with a review — deliberately, so that no small
programming language grows inside a deployment YAML. If a real case exceeds the set,
a safe Python subset via RestrictedPython is the documented escape hatch; it is not
part of v1, because it would cost exactly what makes the closed set valuable: the
startup type check and rules that can be understood at a glance.

**Startup validation**, all fatal: known kinds, known functions, no rule referencing a
field that is neither declared nor produced elsewhere, no duplicate view names, no
collision between a derived and a declared field name, and every date function
applied only to `DATETIME` fields.

## API

Bearer authentication, errors as `application/problem+json`.

| Call | Input | Output |
|---|---|---|
| `GET /catalogue?view_type=…` | — | field list: `key`, `kinds`, `derived`, `description` |
| `POST /lookup` | `{person_uid, view_type, fields}` | projection map with exactly the requested fields |

`/lookup` reads the row `(person_uid, view_type)`, evaluates that view's rules and
projects onto the requested fields. A field the catalogue does not know is an
error, not a silent omission; a field the catalogue knows but that is empty for this
person is simply absent from the response.

No search endpoint, no person listing, no write path. Whoever needs to search reads
through the SQL profile, exactly as HEIDI does today.

### What changes in `edutap.pass_builder`

Its client sends `{person_uid, fields}` and calls `GET /catalogue` without
parameters. Both gain `view_type`; the `data_field` cache and the `/fields` endpoint
carry the dimension. Its `value_type` gives way to `kinds`, which sharpens the
publish check from "is this field known" to "may this field go into an NFC payload".
This was already noted as follow-up work in July, now with the final name.

## Package contract

Own `MetaData` with the copied `NAMING_CONVENTION`, a `Base` class both tables
inherit from, and a `SchemaDefinition` announced through the `edutap.db_definitions`
entry point:

```python
definition = SchemaDefinition(
    name="edutap.data_provider",
    metadata=metadata,
    version_table="alembic_version_data_provider",
)
```

The schema is rendered by `edutap-dbdef create` and watched by `edutap-dbdef check`.
The service creates no table itself.

## Transition

**Big bang, no migration.** This package brings the schema,
`lmu_edutap_data_vzd_webhook` fills `person_view` freshly from the directory, and the
worker writes `pass_state` from Kafka events. No backfill, no dual write, no row
maintained in two worlds. `lmu_edutap_full_view` is switched off on the cutover date;
it is **not modified** — what is needed of its subject matter (LDAP reading, mapping
onto the person model) is written anew in the VZD webhook.

**HEIDI keeps its configuration**, through a compatibility view in the LMU
deployment:

```sql
CREATE VIEW heidi_full_view AS
SELECT person_uid, data, updated_at
FROM person_view WHERE view_type = 'full_view';
```

Without it HEIDI would also see the `mensapass` rows and deliver persons more than
once. The view belongs to the LMU deployment, not to this package: it serves one
consumer that other sites do not have, and `db_definitions` renders tables from
metadata, not site-specific SQL views.

## Architecture

```
src/edutap/data_provider/
    __init__.py      # public exports
    models/
        base.py      # MetaData + Base with the copied naming convention
        db.py        # person_view, pass_state
        dbdef.py     # SchemaDefinition for the entry point
    vocabulary.py    # WalletType, PassLifecycleState, FieldKind
    config.py        # view configuration: parsing and startup validation
    rules.py         # the closed function set and its evaluator
    catalogue.py     # catalogue per view_type, from the configuration
    repository.py    # reading person_view and pass_state
    api/             # FastAPI routers, auth, problem+json errors
    settings.py      # pydantic-settings
```

`rules` and `catalogue` are pure over configuration and payload — testable without a
database. `repository` is the only module that talks to one.

## Testing

Test-first throughout.

* **Unit, no database**: every rule function including null and absence handling, the
  startup type check, configuration validation, projection, the catalogue derived
  from a configuration, and a test asserting that every rule only references fields
  that are declared or produced by another rule.
* **Integration** via `testcontainers[postgres]`: reading rows, derivation over real
  JSONB, the composite key, and the compatibility view returning exactly the
  `full_view` rows.

## Tooling

`uv`; runtime dependencies `fastapi`, `uvicorn`, `sqlalchemy`, `sqlmodel`, `asyncpg`,
`pydantic`, `pydantic-settings`, `pyyaml`. Async service, unlike `db_definitions`.
`ruff` (pinned to one minor), `ty`, `prek`, `tox` over 3.12/3.13/3.14, GitHub Actions
with a separate integration job, Sphinx + MyST following Diataxis, and a Docker test
environment — this one *is* a service.

## Open points

* The VZD webhook must be able to perform a **full initial load** before the cutover;
  event-driven single updates do not fill an empty table. Whether that is an initial
  sync inside the webhook package or a separate tool is LMU design and belongs in its
  own spec.
* The `WalletType` values above supersede the older spellings in `pass_builder`,
  `edutap.heidi_api` and `full_view` (`APPLE`, `GOOGLE`, `SAMSUNG` with `_ACCESS`
  variants). Aligning those three is follow-up work, not a precondition.
* Whether the LMU `full_view` payload's 1:n structures (study programs, employments,
  organisational units) appear in `full_view` as enumerated flat keys is a producer
  decision. This package forbids nested objects; how the producer flattens is its
  own design, and the catalogue simply declares whatever it writes.
* `edutap.pass_builder`'s client change (`view_type`, `kinds`) is a separate plan.
