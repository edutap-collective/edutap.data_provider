# Importing the contract tables — design

**Date:** 2026-08-10
**Status:** decided (A. Loechel), implemented in this change

A record of a decision at a point in time. It is not rewritten to match a later
state; a changed decision gets a new record.

## What changed

This package declared `person_view`, `pass_state` and `pass_instance` and announced
them to `edutap.db_definitions` through an entry point. It now imports them from
`edutap.db_definitions.public.tables` and announces nothing.

The counterpart is
`edutap.db_definitions`' own record, *The contract schema moves here*. The short
version: a reader declaring what other services write had the ownership backwards.
`person_view` is filled by a person spooler, `pass_state` and `pass_instance` by the
pass-state consumer, and this service only reads.

## Why the dependency goes the way it does now

`edutap.db_definitions` is a **runtime** dependency of this package, not a
development one. That looks odd for a tool nobody deploys, and it is why the tool's
own dependencies were split first: its core install is SQLAlchemy, SQLModel and the
shared vocabulary. Alembic and the database driver sit in its `cli` extra and stay
out of this container.

So the runtime dependency is on the *declarations*, not on the tool.

## The vocabulary follows

`vocabulary.py` used to declare `WalletType`, `IssuanceState`, `HolderState`,
`InstanceState` and `FieldKind`, with a docstring noting that these spellings were
the leading ones and that aligning the other copies was follow-up work. That work
happened: `edutap.data_models` carries them now, and the imported tables are typed
with *those* enums.

Keeping a second declaration would have put two `IssuanceState` classes in one
process that compare unequal — the exact drift the shared package exists to end. The
module stays as this package's façade, so `from edutap.data_provider.vocabulary
import …` keeps working; there is simply nothing declared in it any more.

## Two things the move uncovered

**`sqlalchemy[asyncio]` was never declared.** The async engine needs `greenlet`, and
SQLAlchemy leaves it to that extra. It was present only because `sqlmodel` dragged it
in, and `sqlmodel` was a dependency solely for the table classes that just left.
Dropping it made six integration tests fail with *the greenlet library is required*.
An accidental dependency is not a declared one, and this one was load-bearing for
every request the service answers.

**`updated_at` is not maintained by the database**, despite a docstring that said so
in the file this package used to own. `server_default` covers the insert;
`updated_at` is SQLAlchemy's `onupdate`, rendered into the UPDATE that SQLAlchemy
itself issues. There is no trigger. It does not affect this service — it never
writes — but it is a requirement on every writer, and it is recorded in the
declaring package now.

## Tests that moved with the code

`tests/test_models.py` — 238 lines about the *design* of the tables: the composite
primary key, byte collation, the watermark `pass_state` has and `person_view` does
not, the deliberately absent foreign key from a pass to a person, text columns rather
than native enums, the cascade from pass to instance.

Those are tests of the declarations and they belong where the declarations are. They
move to `edutap.db_definitions`, in a change of its own, so that they are never
untested in between. What stays here is what this package does with the tables:
`test_repository.py`, and the observability test that provokes a real `DBAPIError`
from a real statement.

## Python floor

Raised from 3.12 to 3.13. Contagious from `edutap.data_models` through
`edutap.db_definitions`; neither can be depended on with a lower floor.
