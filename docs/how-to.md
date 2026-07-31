# How-to guides

Task-oriented recipes. Each one assumes you already have the service running; the
[tutorial](tutorial.md) gets you there.

## Add a view type

A view type is a slice of the person record cut for one purpose. Adding one is a
change to the view configuration plus a change to what the producer writes.

1. **Declare the fields the consumer may see.** In the file that
   `EDUTAP_DATA_PROVIDER_CONFIG_PATH` points at, add a key under `views`:

   ```yaml
   views:
     library_card:
       description: What the library pass needs
       fields:
         eduperson_principal_name: [STRING, TEXT, NFC]
         display_name: [STRING, TEXT]
         library_id: [STRING, TEXT, BARCODE]
   ```

   The kinds say what a field is *good for*, not what it holds. A field may only go
   into an NFC payload if it declares `NFC`, and `edutap.pass_builder` checks that
   when a template version is published. See the
   [field kinds](reference.md#field-kinds) for the full set.

2. **Restart the service.** The configuration is read and validated once at startup.
   A field name with a dot in it, a view that declares nothing, or a name that is
   both stored and derived stops the process there.

3. **Tell the producer what to write.** The producer must write **every field that
   appears anywhere in the view's configuration** — the declared ones and the ones
   only a rule reads. That is the whole contract; there is no extra bookkeeping and
   no renaming layer. Field names are the standard-native ones (eduPerson, SCHAC,
   dfnEduPerson), multi-valued attributes are arrays, and the payload is flat.

4. **Check the result** before any consumer does:

   ```console
   $ curl -H "Authorization: Bearer $TOKEN" \
       "http://localhost:8000/catalogue?view_type=library_card"
   ```

A row may hold fields the configuration never mentions. They are tolerated and
invisible over the API — but a SQL reader does see them, so cut a dedicated view
rather than pointing an external consumer at `full_view`.

## Write a derivation rule

A derived field is computed from other fields of the *same row*, at read time. Put it
under `derived`, give it kinds and a rule:

```yaml
    derived:
      pass_valid_until:
        kinds: [STRING, TEXT, DATETIME]
        description: At most seven days ahead, never past the role that carries it
        rule: >
          min(add_days(today(), 7),
              coalesce(student_role_valid_until, open_ended),
              coalesce(employee_role_valid_until, open_ended))
```

Read the example inside out: `add_days(today(), 7)` is the refresh cadence, each
`coalesce(...)` is one role's end date with a fallback for a person who does not hold
that role, and `min(...)` takes whichever comes first. A pass is therefore never
valid longer than the role that carries it, and never longer than a week without the
wallet coming back to ask.

The language is closed: the functions in the
[rule function table](reference.md#rule-functions) are all there are, over field
references, literals and named constants. There is no user-defined syntax and no
`eval`. Adding a function is a code change with a review, deliberately — so that no
small programming language grows inside a deployment YAML.

Three things worth knowing while writing one:

* **`9999-12-31` belongs in `constants`, not in the rule.** An unlimited role at LMU
  is written as that date, another site may use a different sentinel, and hard-coding
  it into the package would make the package wrong for the other site. Declared once
  under `constants`, every rule reads it by name and a reader sees immediately that
  it is not a real date:

  ```yaml
  constants:
    open_ended: 9999-12-31
  ```

  A constant also counts as date-like for the startup type check, which is what lets
  `coalesce(student_role_valid_until, open_ended)` sit in a date position.

* **Ask about membership, not about presence.** `exists(employee_role_valid_until)`
  answers whether the payload carries that key — which is a fragile proxy for "this
  person is staff", because it changes with whatever the producer happens to write.
  The robust form is `contains(eduperson_affiliation, 'employee')`.

* **Date functions need declared dates.** `add_days` and `days_between` may only be
  applied to fields that declare `DATETIME`, to constants, or to other calls that
  provably yield a date. Anything else is a configuration error that stops the
  service at startup, rather than a silent string comparison in which `2026-12-01`
  sorts before `2026-2-01`.

Validate a configuration without starting the service:

```console
$ .venv/bin/python -c "
from pathlib import Path
from edutap.data_provider.config import load_config
from edutap.data_provider.validation import validate_config
validate_config(load_config(Path('views.example.yaml')))
print('configuration is valid')
"
```

## Let a SQL consumer read the tables directly

An implementation whose consumers sit in the same database may let them read
`person_view` and `pass_state` directly. This is the optional half of the contract;
the HTTP API is the mandatory half.

Grant read access and nothing else:

```sql
GRANT SELECT ON person_view, pass_state TO heidi_reader;
```

What such a consumer gets is **raw rows**:

* no projection — every key the producer wrote is visible, including the ones the
  catalogue does not expose;
* no derivation — `pass_valid_until` does not exist in any column, because it comes
  into being at read time inside the service;
* no view-type filter — one person has one row per view type, so a query that
  forgets `WHERE view_type = …` returns the same person several times.

A direct reader therefore brings its own post-processing. HEIDI Local is the working
example: it reads a table by `table:`, `id_column:` and `json_columns:`, and maps the
payload onto its own flat model through a `field_map` in its deployment
configuration. That mapping keeps working unchanged — it is exactly the
post-processing this profile expects.

For HEIDI, the LMU deployment adds a compatibility view so that the reader sees one
row per person rather than one per view type:

```sql
CREATE VIEW heidi_full_view AS
SELECT person_uid, data, updated_at
FROM person_view WHERE view_type = 'full_view';
```

That view belongs to the deployment, not to this package: it serves one consumer
that other sites do not have, and `edutap.db_definitions` renders tables from
metadata, not site-specific SQL.

If the consumer sits outside the university, use the API instead. Data minimisation
is a property of what the producer writes into a dedicated view, and the SQL profile
by definition hands over whatever the row contains.
