# Tutorial: from an empty checkout to a first answered lookup

This walks one path from a fresh clone to a `POST /lookup` that answers with a
derived field. It uses the Docker test environment that ships with the package, so
nothing is installed on your machine except the development virtual environment.
Everything you type here is throwaway; the last step deletes it again.

You need Docker and [uv](https://docs.astral.sh/uv/).

## 1. Create the development environment

```console
$ make venv
```

This creates `.venv` and installs the package with its `dev` extra, which brings the
`edutap-dbdef` command you need in step 3.

## 2. Start the database

```console
$ docker compose up -d db
```

The compose file publishes PostgreSQL on port 5432. If something else already
listens there, stop it or change the published port in `compose.yml` before
continuing — the rest of this tutorial talks to the container through
`docker compose exec`, so only this one step cares.

## 3. Render and apply the schema

The service never creates a table. The schema comes from `edutap.db_definitions`,
which reads the table definitions this package announces through an entry point:

```console
$ .venv/bin/edutap-dbdef create --packages edutap.data_provider --out schema.sql
```

Look at `schema.sql`: it contains `person_view` and `pass_state`, their indexes, and
nothing else. Apply it inside the database container:

```console
$ docker compose exec -T db psql -U data_provider -d data_provider < schema.sql
BEGIN
CREATE TABLE
CREATE INDEX
CREATE INDEX
CREATE TABLE
CREATE INDEX
COMMIT
```

## 4. Write one person view row

In a running installation a producer does this — at LMU the VZD webhook, from
directory events. Here you are the producer, once:

```console
$ docker compose exec -T db psql -U data_provider -d data_provider <<'SQL'
INSERT INTO person_view (person_uid, view_type, data) VALUES (
  'a@example.edu',
  'mensapass',
  '{"eduperson_principal_name": "a@example.edu",
    "display_name": "Alex Example",
    "student_role_valid_until": "2026-08-31"}'
);
SQL
INSERT 0 1
```

The payload is flat: no dots in the keys, no nested objects. It matches the
`mensapass` view of `views.example.yaml`, which the next step mounts into the
service.

## 5. Start the service

```console
$ docker compose up -d app
$ curl http://localhost:8000/healthz
{"status":"ok"}
```

If the service had a view configuration it could not use — an unknown field kind, a
rule reading a field nobody declares, date arithmetic on a field that is not a
`DATETIME` — it would refuse to start here rather than answer a wrong validity later.

## 6. Ask what the view offers

Every endpoint except `/healthz` needs the bearer token from `compose.yml`:

```console
$ curl -H "Authorization: Bearer dev-token" \
    "http://localhost:8000/catalogue?view_type=mensapass"
[{"key":"display_name","kinds":["STRING","TEXT"],"derived":false,"description":null},
 {"key":"eduperson_principal_name","kinds":["STRING","TEXT","NFC"],"derived":false,"description":null},
 {"key":"employee_role_valid_until","kinds":["STRING","DATETIME"],"derived":false,"description":null},
 {"key":"pass_valid_until","kinds":["STRING","TEXT","DATETIME"],"derived":true,
  "description":"At most seven days ahead, never past the role that carries it"},
 {"key":"student_role_valid_until","kinds":["STRING","DATETIME"],"derived":false,"description":null}]
```

`pass_valid_until` stands in the list as an equal, with `"derived": true` as its only
mark. No row anywhere holds it.

## 7. Look up one person

```console
$ curl -H "Authorization: Bearer dev-token" -H "Content-Type: application/json" -d '{"person_uid":"a@example.edu","view_type":"mensapass","fields":["display_name","pass_valid_until"]}' http://localhost:8000/lookup
{"display_name":"Alex Example","pass_valid_until":"2026-08-07"}
```

You never stored `pass_valid_until`. Its rule in `views.example.yaml` reads

```text
min(add_days(today(), 7),
    coalesce(student_role_valid_until, open_ended),
    coalesce(employee_role_valid_until, open_ended))
```

so the answer is the earliest of: seven days from today, the end of the student role
you wrote in step 4, and — because this person has no employee role — the named
constant `open_ended`, which the configuration sets to `9999-12-31`. Seven days from
today wins. Run the same call tomorrow and the answer moves with it, without anyone
rewriting a row.

You asked for two fields and received exactly two. `eduperson_principal_name` is in
the catalogue and in the row, and it is not in the answer, because you did not ask
for it.

## 8. Ask for something the view does not offer

```console
$ curl -H "Authorization: Bearer dev-token" -H "Content-Type: application/json" -d '{"person_uid":"a@example.edu","view_type":"mensapass","fields":["salary"]}' http://localhost:8000/lookup
{"title":"Unknown field","status":400,"detail":"View 'mensapass' does not offer: salary."}
```

An unknown field is an error, not a silent omission — a consumer that misspells a
field learns so immediately. The response carries the media type
`application/problem+json`; every error this API raises itself has that shape.

## 9. Tear it down

```console
$ docker compose down -v
$ rm schema.sql
```

## Where to go next

* [How-to guides](how-to.md) — add a view type, write a derivation rule, read the
  tables directly by SQL.
* [Reference](reference.md) — every endpoint, setting, rule function and column.
* [Explanation](explanation.md) — why the service is read-only, and why derivation
  happens at read time.
