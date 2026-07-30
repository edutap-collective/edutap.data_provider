# edutap.data_provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the read-only FastAPI service that delivers person views and pass states — `GET /catalogue` and `POST /lookup` over configured views, with read-time derivation from a closed rule language.

**Architecture:** `config` parses and validates the view YAML; `rules` evaluates a closed function set over a payload; `catalogue` turns a view configuration into the exposed field list; `repository` is the only module that touches the database; `api` wires them into two endpoints. `rules` and `catalogue` are pure functions over configuration and payload and need no database.

**Tech Stack:** Python 3.12+, FastAPI, uvicorn, SQLAlchemy 2 + SQLModel with asyncpg, pydantic v2, pydantic-settings, PyYAML, pytest, testcontainers[postgres], ruff, ty, prek, tox.

**Spec:** `docs/superpowers/specs/2026-07-30-data-provider-design.md`

**Scope note:** This plan builds the service only. The `edutap.pass_builder` client change (`view_type`, `kinds`), the LMU producer `lmu_edutap_data_vzd_webhook`, and the LMU compatibility view are separate work in other repositories.

## Global Constraints

- Python `>=3.12`; tox over 3.12, 3.13, 3.14.
- Runtime dependencies exactly: `fastapi`, `uvicorn`, `sqlalchemy`, `sqlmodel`, `asyncpg`, `pydantic`, `pydantic-settings`, `pyyaml`. No others without a written reason.
- Licence EUPL-1.2; docs, code comments and commit messages in **English**.
- `src/` layout, PEP 420 namespace package: **no** `src/edutap/__init__.py`.
- **The service is read-only.** No `INSERT`, `UPDATE` or `DELETE` anywhere in `src/`, and no table creation — the schema is applied by `edutap.db_definitions`.
- The naming convention is **copied** into `models/base.py`, never imported from `edutap.db_definitions`: importing would give a deployed service a runtime dependency on a tool that is never deployed.
- `wallet_type` and `state` are **text columns** with a `StrEnum` in the model, never native database enums — a new wallet provider must not require a migration in every installation.
- Payload rules, enforced by the catalogue rather than the database: flat, no dotted keys, no nested objects; arrays allowed for genuinely multi-valued attributes.
- The rule language is a **closed** function set. No user-defined expressions, no arithmetic beyond the listed date functions, no new function without a code change.
- Startup validation failures are fatal: the service must not start with an invalid configuration.
- Test-first for every behaviour: failing test, confirm the failure, then implement.
- Async everywhere in the service path (`asyncpg`, `async def`); no blocking calls in request handling.

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml` | packaging, dependencies, entry point, ruff/ty/pytest config |
| `src/edutap/data_provider/vocabulary.py` | `WalletType`, `PassLifecycleState`, `FieldKind` |
| `src/edutap/data_provider/models/base.py` | copied naming convention, own `MetaData`, `Base` |
| `src/edutap/data_provider/models/db.py` | `PersonView`, `PassState` |
| `src/edutap/data_provider/models/dbdef.py` | `SchemaDefinition` for the `edutap.db_definitions` entry point |
| `src/edutap/data_provider/config.py` | view configuration: models, YAML loading, structural validation |
| `src/edutap/data_provider/rules.py` | rule parsing, the closed function set, evaluation |
| `src/edutap/data_provider/validation.py` | cross-validation of rules against the catalogue and kinds |
| `src/edutap/data_provider/catalogue.py` | catalogue entries per view type |
| `src/edutap/data_provider/settings.py` | pydantic-settings |
| `src/edutap/data_provider/repository.py` | the only module that reads the database |
| `src/edutap/data_provider/api/` | app factory, auth, problem+json errors, routers |
| `tests/` | one module per source module; integration tests marked `integration` |
| `Dockerfile`, `compose.yml` | Docker test environment (this one is a service) |
| `docs/` | Sphinx + MyST, Diataxis |

---

### Task 1: Packaging, tooling and the application skeleton

**Files:**
- Modify: `pyproject.toml`
- Create: `src/edutap/data_provider/__init__.py`, `src/edutap/data_provider/api/__init__.py`, `src/edutap/data_provider/api/app.py`
- Create: `Makefile`, `tox.ini`, `.pre-commit-config.yaml`, `.github/workflows/ci.yml`
- Test: `tests/test_app_skeleton.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `api.app.create_app() -> FastAPI`; `edutap.data_provider.__version__: str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_app_skeleton.py
from fastapi.testclient import TestClient

from edutap.data_provider.api.app import create_app


def test_healthz_reports_ok():
    with TestClient(create_app()) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_version_is_exposed():
    from edutap.data_provider import __version__

    assert __version__
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_app_skeleton.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'edutap.data_provider'`

- [ ] **Step 3: Write `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling>=1.27"]
build-backend = "hatchling.build"

[project]
name = "edutap.data_provider"
version = "0.1.0"
description = "Read-only service delivering person views and pass states for eduTAP"
readme = "README.md"
requires-python = ">=3.12"
license = "EUPL-1.2"
authors = [{ name = "eduTAP" }]
dependencies = [
    "asyncpg>=0.29",
    "fastapi>=0.115",
    "pydantic>=2.8",
    "pydantic-settings>=2.4",
    "pyyaml>=6",
    "sqlalchemy>=2.0",
    "sqlmodel>=0.0.22",
    "uvicorn[standard]>=0.30",
]

[project.optional-dependencies]
dev = [
    "httpx>=0.27",
    "pdbp",
    "pytest>=8.2",
    "pytest-asyncio>=0.24",
    "ruff>=0.16,<0.17",
    "testcontainers[postgres]>=4.8",
    "ty",
]
docs = ["myst-parser", "sphinx>=8"]

[project.entry-points."edutap.db_definitions"]
schema = "edutap.data_provider.models.dbdef:definition"

[tool.hatch.build.targets.wheel]
packages = ["src/edutap"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["integration: needs a PostgreSQL container"]
addopts = "-m 'not integration'"
asyncio_mode = "auto"

[tool.ruff]
line-length = 100
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "W", "B", "I", "UP", "D", "S"]
ignore = ["D203", "D213"]

[tool.ruff.lint.per-file-ignores]
"tests/*" = ["D", "S101"]
```

- [ ] **Step 4: Write the package skeleton**

```python
# src/edutap/data_provider/__init__.py
"""Read-only service delivering person views and pass states."""

from importlib.metadata import version


__version__ = version("edutap.data_provider")

__all__ = ["__version__"]
```

```python
# src/edutap/data_provider/api/__init__.py
"""HTTP surface of the data provider."""
```

```python
# src/edutap/data_provider/api/app.py
"""Application factory."""

from fastapi import APIRouter
from fastapi import FastAPI


health_router = APIRouter()


@health_router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Report that the process is up."""
    return {"status": "ok"}


def create_app() -> FastAPI:
    """Build the FastAPI application."""
    app = FastAPI(title="eduTAP data provider", version="0.1.0")
    app.include_router(health_router)
    return app
```

- [ ] **Step 5: Install and run the test**

Run: `uv venv && uv pip install -U -e ".[dev]" && .venv/bin/python -m pytest tests/test_app_skeleton.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Write the tooling files**

```makefile
# Makefile
# Tools run from .venv, not through `uv run`: this package declares an entry point
# group that uv resolves against the whole environment, and a bare `uv run` can fail
# in a checkout where sibling eduTAP packages are not installed.
PYTHON := .venv/bin/python
VENV   := .venv

.DEFAULT_GOAL := help
.PHONY: help venv lint reformat test-local test-integration run

help: ## Show available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk -F':.*?## ' '{printf "  %-18s %s\n", $$1, $$2}'

venv: ## Create .venv and install the package with its dev extra
	test -d $(VENV) || uv venv
	uv pip install -U -e ".[dev]"

lint: venv ## Run ruff checks and the type checker
	$(PYTHON) -m ruff check src tests
	$(PYTHON) -m ruff format --check src tests
	$(PYTHON) -m ty check src

reformat: venv ## Autoformat and autofix
	$(PYTHON) -m ruff format src tests
	$(PYTHON) -m ruff check --fix src tests

test-local: venv ## Unit tests, no database needed
	$(PYTHON) -m pytest -v

test-integration: venv ## Integration tests against a PostgreSQL container
	$(PYTHON) -m pytest -m integration -v

run: venv ## Start the service against the compose environment
	$(PYTHON) -m uvicorn edutap.data_provider.api.app:create_app --factory --reload
```

```ini
; tox.ini
[tox]
envlist = py312,py313,py314,lint
isolated_build = true

[testenv]
runner = uv-venv-runner
extras = dev
commands = pytest -v {posargs}

[testenv:lint]
basepython = py312
commands =
    ruff check src tests
    ruff format --check src tests
    ty check src
```

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.16.0
    hooks:
      - id: ruff-check
        args: [--fix]
      - id: ruff-format
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v6.0.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-toml
```

```yaml
# .github/workflows/ci.yml
name: CI
on:
  push:
    branches: [main]
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python: ["3.12", "3.13", "3.14"]
    steps:
      - uses: actions/checkout@v5
      - uses: astral-sh/setup-uv@v7
        with:
          python-version: ${{ matrix.python }}
      - run: uv pip install --system -e ".[dev]"
      - run: pytest -v
  integration:
    # The default run excludes these (addopts), so without this job the
    # database-backed behaviour would never be exercised in CI.
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: astral-sh/setup-uv@v7
        with:
          python-version: "3.12"
      - run: uv pip install --system -e ".[dev]"
      - run: pytest -m integration -v
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: astral-sh/setup-uv@v7
        with:
          python-version: "3.12"
      - run: uv pip install --system -e ".[dev]"
      - run: ruff check src tests
      - run: ruff format --check src tests
      - run: ty check src
```

- [ ] **Step 7: Verify lint and tests**

Run: `make lint && make test-local`
Expected: both pass

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml src tests Makefile tox.ini .pre-commit-config.yaml .github
git commit -m "feat: add packaging, tooling and the application skeleton"
```

---

### Task 2: The eduTAP vocabulary

**Files:**
- Create: `src/edutap/data_provider/vocabulary.py`
- Test: `tests/test_vocabulary.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `WalletType(StrEnum)`, `PassLifecycleState(StrEnum)`, `FieldKind(StrEnum)`, all importable from `edutap.data_provider`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_vocabulary.py
from edutap.data_provider.vocabulary import FieldKind, PassLifecycleState, WalletType


def test_wallet_types_carry_the_edutap_spellings():
    assert WalletType.GOOGLE_ST == "GOOGLE_ST"
    assert WalletType.APPLE_VAS == "APPLE_VAS"
    assert {"GOOGLE_ACCESS", "APPLE_ACCESS", "APPLE_IDENTITY"} <= {w.value for w in WalletType}


def test_lifecycle_states_cover_the_pass_life():
    assert {s.value for s in PassLifecycleState} == {
        "NEW",
        "INSTALL_PENDING",
        "UPDATE_PENDING",
        "DELETE_PENDING",
        "ACTIVE",
        "INACTIVE",
    }


def test_field_kinds_say_what_a_field_is_good_for():
    assert {k.value for k in FieldKind} == {
        "STRING",
        "TEXT",
        "DATETIME",
        "LINK",
        "NFC",
        "BARCODE",
        "IMAGE",
    }


def test_values_compare_as_plain_strings():
    assert WalletType("APPLE_VAS") == "APPLE_VAS"
    assert PassLifecycleState("ACTIVE") in ("ACTIVE", "INACTIVE")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_vocabulary.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'edutap.data_provider.vocabulary'`

- [ ] **Step 3: Write the implementation**

```python
# src/edutap/data_provider/vocabulary.py
"""The eduTAP vocabulary for wallets, pass lifecycle and field kinds.

Consumers COPY these values rather than importing them. Importing would point a
consumer's dependency at the service it consumes — `edutap.pass_builder` would
depend on the data provider. The same rule applies to the naming convention in
`models/base.py`, for the same reason.

These spellings supersede the older ones in `edutap.pass_builder`,
`edutap.heidi_api` and `lmu_edutap_full_view` (`APPLE`, `GOOGLE`, `SAMSUNG` with
`_ACCESS` variants). Aligning those is follow-up work.
"""

from enum import StrEnum


class WalletType(StrEnum):
    """Which wallet technology a pass was issued for."""

    GOOGLE_ST = "GOOGLE_ST"
    GOOGLE_ACCESS = "GOOGLE_ACCESS"
    APPLE_VAS = "APPLE_VAS"
    APPLE_ACCESS = "APPLE_ACCESS"
    APPLE_IDENTITY = "APPLE_IDENTITY"
    SAMSUNG_ST = "SAMSUNG_ST"
    SAMSUNG_ACCESS = "SAMSUNG_ACCESS"


class PassLifecycleState(StrEnum):
    """Where a pass stands in its life.

    The data provider stores and delivers these; it never validates a transition.
    """

    NEW = "NEW"
    INSTALL_PENDING = "INSTALL_PENDING"
    UPDATE_PENDING = "UPDATE_PENDING"
    DELETE_PENDING = "DELETE_PENDING"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class FieldKind(StrEnum):
    """What a field is good for — not what it holds.

    `edutap.pass_builder` validates mapping rules against these when a template
    version is published: a field may only go into an NFC payload if it declares
    NFC.
    """

    STRING = "STRING"
    TEXT = "TEXT"
    DATETIME = "DATETIME"
    LINK = "LINK"
    NFC = "NFC"
    BARCODE = "BARCODE"
    IMAGE = "IMAGE"
```

- [ ] **Step 4: Export from the package root**

```python
# src/edutap/data_provider/__init__.py — replace the module with this
"""Read-only service delivering person views and pass states."""

from importlib.metadata import version

from .vocabulary import FieldKind
from .vocabulary import PassLifecycleState
from .vocabulary import WalletType


__version__ = version("edutap.data_provider")

__all__ = ["FieldKind", "PassLifecycleState", "WalletType", "__version__"]
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_vocabulary.py -v && make lint`
Expected: PASS (4 tests), lint clean

- [ ] **Step 6: Commit**

```bash
git add src/edutap/data_provider/vocabulary.py src/edutap/data_provider/__init__.py tests/test_vocabulary.py
git commit -m "feat: add the eduTAP vocabulary for wallets, lifecycle and field kinds"
```

---

### Task 3: The tables and the `db_definitions` entry point

**Files:**
- Create: `src/edutap/data_provider/models/__init__.py`, `models/base.py`, `models/db.py`, `models/dbdef.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: `WalletType`, `PassLifecycleState` from Task 2.
- Produces:
  - `models.base.NAMING_CONVENTION: dict[str, str]`, `models.base.metadata: MetaData`, `models.base.Base`
  - `models.db.PersonView` (`person_uid`, `view_type`, `data`, `updated_at`), `models.db.PassState` (`pass_id`, `person_uid`, `wallet_type`, `state`, `pass_template`, `pass_template_variant`, `created_at`, `updated_at`)
  - `models.dbdef.definition` — the object the entry point resolves to

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models.py
import sqlalchemy as sa

from edutap.data_provider.models.base import NAMING_CONVENTION, metadata
from edutap.data_provider.models.db import PassState, PersonView


def test_tables_live_on_the_package_metadata_only():
    from sqlmodel import SQLModel

    assert set(metadata.tables) == {"person_view", "pass_state"}
    assert "person_view" not in SQLModel.metadata.tables


def test_naming_convention_is_the_canonical_one():
    assert dict(metadata.naming_convention) == NAMING_CONVENTION


def test_person_view_has_a_composite_primary_key():
    table = metadata.tables["person_view"]
    assert [column.name for column in table.primary_key.columns] == ["person_uid", "view_type"]


def test_person_view_keys_use_byte_collation():
    table = metadata.tables["person_view"]
    for name in ("person_uid", "view_type"):
        assert table.columns[name].type.collation == "C"


def test_person_view_indexes_view_type_for_whole_view_reads():
    table = metadata.tables["person_view"]
    indexed = {tuple(column.name for column in index.columns) for index in table.indexes}
    assert ("view_type",) in indexed


def test_pass_state_identifier_is_a_string_not_a_uuid():
    column = metadata.tables["pass_state"].columns["pass_id"]
    assert isinstance(column.type, sa.String)
    assert column.type.length == 255
    assert column.primary_key


def test_pass_state_has_no_foreign_key_to_the_person():
    assert metadata.tables["pass_state"].foreign_keys == set()


def test_pass_state_indexes_the_question_readers_ask():
    table = metadata.tables["pass_state"]
    indexed = {tuple(column.name for column in index.columns) for index in table.indexes}
    assert ("person_uid", "pass_template", "wallet_type") in indexed


def test_vocabulary_columns_are_text_not_native_enums():
    table = metadata.tables["pass_state"]
    for name in ("wallet_type", "state"):
        assert isinstance(table.columns[name].type, sa.String)
        assert not isinstance(table.columns[name].type, sa.Enum)


def test_variant_is_optional_because_a_default_exists():
    assert metadata.tables["pass_state"].columns["pass_template_variant"].nullable


def test_models_are_usable_as_python_objects():
    view = PersonView(person_uid="x@lmu.de", view_type="full_view", data={"surname": "Doe"})
    assert view.data["surname"] == "Doe"
    state = PassState(
        pass_id="3388000000022195611.abc",
        person_uid="x@lmu.de",
        wallet_type="GOOGLE_ST",
        state="ACTIVE",
        pass_template="mensapass",
    )
    assert state.pass_template_variant is None
```

- [ ] **Step 2: Write the entry-point test**

```python
# tests/test_models.py — append
def test_schema_definition_announces_this_package():
    from edutap.data_provider.models.dbdef import definition

    assert definition.name == "edutap.data_provider"
    assert definition.metadata is metadata
    assert definition.version_table == "alembic_version_data_provider"
    assert sorted(definition.table_names) == ["pass_state", "person_view"]


def test_entry_point_resolves_to_the_definition():
    from importlib.metadata import entry_points

    from edutap.data_provider.models.dbdef import definition

    points = [p for p in entry_points(group="edutap.db_definitions") if p.name == "schema"]
    assert points, "the edutap.db_definitions entry point is not installed"
    assert points[0].load() is definition
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'edutap.data_provider.models'`

- [ ] **Step 4: Write the base module**

```python
# src/edutap/data_provider/models/__init__.py
"""Database models of the data provider."""
```

```python
# src/edutap/data_provider/models/base.py
"""Package-local metadata and declarative base.

The naming convention is COPIED from `edutap.db_definitions`, deliberately not
imported: importing would give this deployed service a runtime dependency on a tool
that is never deployed. `edutap-dbdef check` verifies that every package uses the
same convention.

The metadata is package-local because `SQLModel.metadata` is a process-wide
singleton — a generator that cannot tell packages apart cannot order, split or diff
them.
"""

from sqlalchemy import MetaData
from sqlmodel import SQLModel


NAMING_CONVENTION: dict[str, str] = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Base(SQLModel):
    """Declarative base binding this package's tables to its own metadata."""

    metadata = metadata
```

- [ ] **Step 5: Write the tables**

```python
# src/edutap/data_provider/models/db.py
"""The two tables the data provider owns."""

from datetime import datetime
from datetime import timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field

from ..vocabulary import PassLifecycleState
from ..vocabulary import WalletType
from .base import Base


def _utcnow() -> datetime:
    """Timezone-aware now, for the Python-side default."""
    return datetime.now(tz=timezone.utc)


def _timestamp(on_update: bool = False) -> sa.Column:
    """Build a timestamptz column maintained by the database."""
    kwargs: dict[str, Any] = {"server_default": sa.func.now()}
    if on_update:
        kwargs["onupdate"] = sa.func.now()
    return sa.Column(sa.DateTime(timezone=True), nullable=False, **kwargs)


class PersonView(Base, table=True):
    """One view of one person: the payload a consumer of this view type may see."""

    __tablename__ = "person_view"
    __table_args__ = (sa.Index("ix_person_view_view_type", "view_type"),)

    person_uid: str = Field(
        sa_column=sa.Column(sa.String(64, collation="C"), primary_key=True),
        description=(
            "Person identifier, uniquely determinable by the university: ePPN, UUID or "
            "hash. Never interpreted here. Byte collation so comparison and index order "
            "do not depend on a locale."
        ),
    )
    view_type: str = Field(
        sa_column=sa.Column(sa.String(64, collation="C"), primary_key=True),
        description="`full_view` or a speaking slice such as `mensapass`.",
    )
    data: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=sa.Column(JSONB, nullable=False),
        description="Flat payload, standard-native names, arrays for multi-valued attributes.",
    )
    updated_at: datetime = Field(default_factory=_utcnow, sa_column=_timestamp(on_update=True))


class PassState(Base, table=True):
    """One issued pass and where it stands in its life."""

    __tablename__ = "pass_state"
    __table_args__ = (
        sa.Index("ix_pass_state_person_uid", "person_uid"),
        sa.Index("ix_pass_state_person_template_wallet", "person_uid", "pass_template", "wallet_type"),
    )

    pass_id: str = Field(
        sa_column=sa.Column(sa.String(255), primary_key=True),
        description=(
            "The provider's pass identifier. Not a UUID column: usually a UUID, but "
            "Google Wallet object identifiers carry a prefix and suffix."
        ),
    )
    person_uid: str = Field(
        sa_column=sa.Column(sa.String(64, collation="C"), nullable=False),
        description="No foreign key: a pass exists whether or not a view row currently does.",
    )
    wallet_type: WalletType = Field(
        sa_column=sa.Column(sa.String(32), nullable=False),
        description="Text column, not a native enum — a new wallet provider must not force a migration.",
    )
    state: PassLifecycleState = Field(
        sa_column=sa.Column(sa.String(32), nullable=False),
        description="Stored and delivered, never validated here.",
    )
    pass_template: str = Field(
        sa_column=sa.Column(sa.String(64), nullable=False),
        description="Speaking template key, matching Template.key in edutap.pass_builder.",
    )
    pass_template_variant: str | None = Field(
        default=None,
        sa_column=sa.Column(sa.String(64), nullable=True),
        description="Variant key; empty means the default variant, modelled as is_default there.",
    )
    created_at: datetime = Field(default_factory=_utcnow, sa_column=_timestamp())
    updated_at: datetime = Field(default_factory=_utcnow, sa_column=_timestamp(on_update=True))
```

- [ ] **Step 6: Write the schema definition**

```python
# src/edutap/data_provider/models/dbdef.py
"""What this package tells `edutap.db_definitions` about its tables."""

from edutap.db_definitions import SchemaDefinition

from . import db  # noqa: F401  importing registers the tables on the metadata
from .base import metadata


definition = SchemaDefinition(
    name="edutap.data_provider",
    metadata=metadata,
    version_table="alembic_version_data_provider",
)
```

Note on the import: `edutap.db_definitions` is a **development** dependency here, not
a runtime one — the service never calls it. Add it to the `dev` extra in
`pyproject.toml`, not to `dependencies`:

```toml
dev = [
    "edutap.db_definitions",
    "httpx>=0.27",
    …
]
```

If the package is not installed in the environment, `models/dbdef.py` must not break
the service. Guard the import:

```python
try:
    from edutap.db_definitions import SchemaDefinition
except ModuleNotFoundError:  # pragma: no cover - the service does not need the tool
    SchemaDefinition = None  # type: ignore[assignment]
```

and skip the two entry-point tests with `pytest.importorskip("edutap.db_definitions")`.

- [ ] **Step 7: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_models.py -v && make lint`
Expected: PASS (12 tests), lint clean

- [ ] **Step 8: Commit**

```bash
git add src/edutap/data_provider/models tests/test_models.py pyproject.toml
git commit -m "feat: add the person view and pass state tables"
```

---

### Task 4: View configuration — models, loading, structural validation

**Files:**
- Create: `src/edutap/data_provider/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `FieldKind` from Task 2.
- Produces:
  - `ConfigError(Exception)`
  - `FieldSpec(kinds: list[FieldKind], description: str | None)`
  - `DerivedSpec(kinds: list[FieldKind], rule: str, description: str | None)`
  - `ViewSpec(description: str | None, fields: dict[str, FieldSpec], derived: dict[str, DerivedSpec])`
  - `ProviderConfig(constants: dict[str, Any], views: dict[str, ViewSpec])`
  - `load_config(path: Path) -> ProviderConfig`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
import pytest

from edutap.data_provider.config import ConfigError, load_config
from edutap.data_provider.vocabulary import FieldKind

CONFIG = """
constants:
  open_ended: 9999-12-31

views:
  full_view:
    description: Complete record
    fields:
      surname: [STRING, TEXT]
      mail: [STRING, TEXT, LINK]
  mensapass:
    fields:
      display_name: [STRING, TEXT]
    derived:
      pass_valid_until:
        kinds: [STRING, TEXT, DATETIME]
        rule: add_days(today(), 7)
"""


def write(tmp_path, text):
    path = tmp_path / "views.yaml"
    path.write_text(text)
    return path


def test_loads_views_and_fields(tmp_path):
    config = load_config(write(tmp_path, CONFIG))
    assert sorted(config.views) == ["full_view", "mensapass"]
    assert config.views["full_view"].fields["mail"].kinds == [
        FieldKind.STRING,
        FieldKind.TEXT,
        FieldKind.LINK,
    ]


def test_loads_a_derived_field_with_its_rule(tmp_path):
    config = load_config(write(tmp_path, CONFIG))
    derived = config.views["mensapass"].derived["pass_valid_until"]
    assert derived.rule == "add_days(today(), 7)"
    assert FieldKind.DATETIME in derived.kinds


def test_constants_keep_their_yaml_types(tmp_path):
    import datetime

    config = load_config(write(tmp_path, CONFIG))
    assert config.constants["open_ended"] == datetime.date(9999, 12, 31)


def test_unknown_kind_is_fatal(tmp_path):
    text = CONFIG.replace("[STRING, TEXT, LINK]", "[STRING, MAGIC]")
    with pytest.raises(ConfigError, match="MAGIC"):
        load_config(write(tmp_path, text))


def test_a_derived_name_colliding_with_a_field_is_fatal(tmp_path):
    text = CONFIG.replace("      display_name: [STRING, TEXT]", "      pass_valid_until: [STRING]")
    with pytest.raises(ConfigError, match="pass_valid_until"):
        load_config(write(tmp_path, text))


def test_a_view_without_fields_or_derived_is_fatal(tmp_path):
    with pytest.raises(ConfigError, match="empty"):
        load_config(write(tmp_path, "views:\n  ghost: {}\n"))


def test_a_missing_file_is_fatal(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "absent.yaml")


def test_dotted_or_nested_field_names_are_rejected(tmp_path):
    text = CONFIG.replace("      surname: [STRING, TEXT]", "      person.surname: [STRING]")
    with pytest.raises(ConfigError, match="flat"):
        load_config(write(tmp_path, text))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'edutap.data_provider.config'`

- [ ] **Step 3: Write the implementation**

```python
# src/edutap/data_provider/config.py
"""View configuration: what a view exposes and how derived fields are computed."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel
from pydantic import ValidationError

from .vocabulary import FieldKind


class ConfigError(Exception):
    """The view configuration cannot be used. Fatal at startup."""


class FieldSpec(BaseModel):
    """A field the producer writes and the catalogue exposes."""

    kinds: list[FieldKind]
    description: str | None = None


class DerivedSpec(BaseModel):
    """A field computed at read time from other fields of the same row."""

    kinds: list[FieldKind]
    rule: str
    description: str | None = None


class ViewSpec(BaseModel):
    """One view type: what it exposes, stored and derived."""

    description: str | None = None
    fields: dict[str, FieldSpec] = {}
    derived: dict[str, DerivedSpec] = {}


class ProviderConfig(BaseModel):
    """The whole configuration: named constants and the views."""

    constants: dict[str, Any] = {}
    views: dict[str, ViewSpec]


def _normalise_fields(raw: dict[str, Any]) -> dict[str, Any]:
    """Accept the short form `name: [KIND, …]` next to the long mapping form."""
    fields = {}
    for name, value in (raw or {}).items():
        fields[name] = {"kinds": value} if isinstance(value, list) else value
    return fields


def _check_flat_names(view_name: str, names: list[str]) -> None:
    for name in names:
        if "." in name or not name.replace("_", "").isalnum():
            raise ConfigError(
                f"View {view_name!r}: field name {name!r} is not flat. Payloads carry flat "
                "keys — no dots, no nested objects."
            )


def load_config(path: Path) -> ProviderConfig:
    """Load and structurally validate the view configuration."""
    if not path.is_file():
        raise ConfigError(f"View configuration not found: {path}")
    raw = yaml.safe_load(path.read_text()) or {}
    for view in (raw.get("views") or {}).values():
        if isinstance(view, dict) and "fields" in view:
            view["fields"] = _normalise_fields(view["fields"])
    try:
        config = ProviderConfig.model_validate(raw)
    except ValidationError as error:
        raise ConfigError(f"Invalid view configuration: {error}") from error

    for name, view in config.views.items():
        if not view.fields and not view.derived:
            raise ConfigError(f"View {name!r} is empty: it exposes no fields.")
        _check_flat_names(name, [*view.fields, *view.derived])
        collisions = set(view.fields) & set(view.derived)
        if collisions:
            raise ConfigError(
                f"View {name!r}: {', '.join(sorted(collisions))} is both a stored and a "
                "derived field. A name means one thing."
            )
    return config
```

Note: an unknown kind raises through pydantic's enum validation, which the
`ConfigError` wrapper re-raises with the offending value in the message — that is
what `test_unknown_kind_is_fatal` asserts.

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_config.py -v && make lint`
Expected: PASS (8 tests), lint clean

- [ ] **Step 5: Commit**

```bash
git add src/edutap/data_provider/config.py tests/test_config.py
git commit -m "feat: load and structurally validate the view configuration"
```

---

### Task 5: The rule language

**Files:**
- Create: `src/edutap/data_provider/rules.py`
- Test: `tests/test_rules.py`

**Interfaces:**
- Consumes: nothing (pure over payload and constants).
- Produces:
  - `RuleError(Exception)`
  - `parse_rule(source: str) -> ast.Expression` — raises `RuleError` on anything outside the closed set
  - `evaluate(expression: ast.Expression, payload: dict[str, Any], constants: dict[str, Any], datetime_fields: set[str]) -> Any`
  - `FUNCTIONS: dict[str, Signature]` where `Signature` records argument and return types for Task 6

**Why an AST rather than a parser:** `ast.parse(source, mode="eval")` gives a tree for
free, and walking it with a whitelist is what makes the set *closed* — anything the
whitelist does not name is rejected before evaluation. No `eval`, no
`RestrictedPython`, no hand-written parser.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rules.py
import datetime

import pytest

from edutap.data_provider.rules import RuleError, evaluate, parse_rule

CONSTANTS = {"open_ended": datetime.date(9999, 12, 31)}
DATETIME_FIELDS = {"student_role_valid_until", "employee_role_valid_until"}


def run(source, payload=None, today=None):
    expression = parse_rule(source)
    return evaluate(
        expression,
        payload or {},
        CONSTANTS,
        DATETIME_FIELDS,
        today=today or datetime.date(2026, 7, 30),
    )


def test_field_reference_returns_the_payload_value():
    assert run("surname", {"surname": "Doe"}) == "Doe"


def test_a_missing_field_is_none_not_an_error():
    assert run("surname", {}) is None


def test_named_constant_resolves():
    assert run("open_ended") == datetime.date(9999, 12, 31)


def test_coalesce_takes_the_first_present_value():
    assert run("coalesce(a, b, 'fallback')", {"b": "second"}) == "second"
    assert run("coalesce(a, b, 'fallback')", {}) == "fallback"


def test_datetime_fields_are_parsed_into_real_dates():
    value = run("student_role_valid_until", {"student_role_valid_until": "2026-09-30"})
    assert value == datetime.date(2026, 9, 30)


def test_add_days_computes_on_real_dates():
    assert run("add_days(today(), 7)") == datetime.date(2026, 8, 6)


def test_days_between_returns_a_number():
    payload = {"student_role_valid_until": "2026-08-06"}
    assert run("days_between(student_role_valid_until, today())", payload) == 7


def test_min_picks_the_earlier_date():
    payload = {"student_role_valid_until": "2026-08-02"}
    assert run(
        "min(add_days(today(), 7), coalesce(student_role_valid_until, open_ended))", payload
    ) == datetime.date(2026, 8, 2)


def test_the_seven_day_rule_with_an_open_ended_role():
    rule = (
        "min(add_days(today(), 7),"
        " coalesce(student_role_valid_until, open_ended),"
        " coalesce(employee_role_valid_until, open_ended))"
    )
    assert run(rule, {}) == datetime.date(2026, 8, 6)


def test_if_branches_on_a_condition():
    rule = "if(exists(employee_role_valid_until), 'employee', 'other')"
    assert run(rule, {"employee_role_valid_until": "2027-01-01"}) == "employee"
    assert run(rule, {}) == "other"


def test_exists_and_is_null_are_different_questions():
    assert run("exists(mail)", {"mail": None}) is True
    assert run("is_null(mail)", {"mail": None}) is True
    assert run("exists(mail)", {}) is False


def test_contains_checks_membership_in_an_array():
    payload = {"eduperson_affiliation": ["member", "student"]}
    assert run("contains(eduperson_affiliation, 'student')", payload) is True
    assert run("contains(eduperson_affiliation, 'employee')", payload) is False


def test_first_and_join_work_on_arrays():
    payload = {"mail": ["a@lmu.de", "b@lmu.de"]}
    assert run("first(mail)", payload) == "a@lmu.de"
    assert run("join(', ', mail)", payload) == "a@lmu.de, b@lmu.de"


def test_comparisons_return_booleans():
    payload = {"student_role_valid_until": "2026-08-02"}
    assert run("lt(student_role_valid_until, add_days(today(), 7))", payload) is True
    assert run("gt(student_role_valid_until, add_days(today(), 7))", payload) is False
    assert run("eq('a', 'a')") is True


def test_an_unknown_function_is_rejected_at_parse_time():
    with pytest.raises(RuleError, match="unknown_function"):
        parse_rule("unknown_function(a)")


def test_arithmetic_is_rejected():
    with pytest.raises(RuleError, match="not allowed"):
        parse_rule("a + 1")


def test_attribute_access_is_rejected():
    with pytest.raises(RuleError, match="not allowed"):
        parse_rule("a.b")


def test_a_syntactically_broken_rule_is_rejected():
    with pytest.raises(RuleError, match="parse"):
        parse_rule("min(")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_rules.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'edutap.data_provider.rules'`

- [ ] **Step 3: Write the implementation**

```python
# src/edutap/data_provider/rules.py
"""The closed rule language: parsing and evaluation.

A rule is a Python expression restricted to a whitelist of function calls, field
references, named constants and literals. `ast.parse` supplies the tree; the
whitelist is what makes the set closed. There is no `eval` and no user-defined
syntax: anything the whitelist does not name is rejected before evaluation.

Adding a function is a code change with a review — deliberately, so that no small
programming language grows inside a deployment YAML.
"""

import ast
import datetime
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


class RuleError(Exception):
    """A rule is outside the closed language, or cannot be evaluated."""


@dataclass(frozen=True)
class Signature:
    """What a function accepts and returns, for the startup type check."""

    name: str
    returns: str  # "date" | "number" | "boolean" | "string" | "any"
    date_arguments: tuple[int, ...] = ()  # positions that must be dates
    variadic: bool = False


FUNCTIONS: dict[str, Signature] = {
    "today": Signature("today", "date"),
    "now": Signature("now", "date"),
    "coalesce": Signature("coalesce", "any", variadic=True),
    "if": Signature("if", "any"),
    "exists": Signature("exists", "boolean"),
    "is_null": Signature("is_null", "boolean"),
    "is_empty": Signature("is_empty", "boolean"),
    "eq": Signature("eq", "boolean"),
    "lt": Signature("lt", "boolean"),
    "gt": Signature("gt", "boolean"),
    "contains": Signature("contains", "boolean"),
    "add_days": Signature("add_days", "date", date_arguments=(0,)),
    "days_between": Signature("days_between", "number", date_arguments=(0, 1)),
    "min": Signature("min", "any", variadic=True),
    "max": Signature("max", "any", variadic=True),
    "first": Signature("first", "any"),
    "join": Signature("join", "string"),
}


def parse_rule(source: str) -> ast.Expression:
    """Parse a rule and reject everything outside the closed language."""
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as error:
        raise RuleError(f"Cannot parse rule {source!r}: {error}") from error

    for node in ast.walk(tree):
        if isinstance(node, ast.Expression | ast.Name | ast.Load | ast.Constant):
            continue
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise RuleError(f"Only named function calls are allowed in {source!r}.")
            if node.func.id not in FUNCTIONS:
                raise RuleError(
                    f"Rule {source!r} calls {node.func.id!r}, which is not one of: "
                    f"{', '.join(sorted(FUNCTIONS))}."
                )
            if node.keywords:
                raise RuleError(f"Keyword arguments are not allowed in {source!r}.")
            continue
        raise RuleError(
            f"{type(node).__name__} is not allowed in a rule. Rule {source!r} may only use "
            "function calls, field references, constants and literals."
        )
    return tree


def _as_date(value: Any) -> datetime.date | None:
    """Turn an ISO string into a real date; pass dates through; None stays None."""
    if value is None or isinstance(value, datetime.date):
        return value
    if isinstance(value, str):
        try:
            return datetime.date.fromisoformat(value[:10])
        except ValueError as error:
            raise RuleError(f"{value!r} is not an ISO date.") from error
    raise RuleError(f"{value!r} cannot be read as a date.")


def _present(values: Sequence[Any]) -> list[Any]:
    return [value for value in values if value is not None]


def evaluate(
    expression: ast.Expression,
    payload: dict[str, Any],
    constants: dict[str, Any],
    datetime_fields: set[str],
    today: datetime.date | None = None,
) -> Any:
    """Evaluate a parsed rule against one payload."""
    reference_day = today or datetime.date.today()

    def resolve(node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return resolve(node.body)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in constants:
                return constants[node.id]
            value = payload.get(node.id)
            return _as_date(value) if node.id in datetime_fields else value
        if isinstance(node, ast.Call):
            return call(node)
        raise RuleError(f"{type(node).__name__} cannot be evaluated.")

    def call(node: ast.Call) -> Any:
        name = node.func.id  # type: ignore[union-attr]  parse_rule guarantees a Name
        if name == "if":
            condition, then, otherwise = node.args
            return resolve(then) if resolve(condition) else resolve(otherwise)
        if name == "exists":
            target = node.args[0]
            return isinstance(target, ast.Name) and target.id in payload
        arguments = [resolve(argument) for argument in node.args]
        return apply(name, arguments)

    def apply(name: str, arguments: list[Any]) -> Any:  # noqa: PLR0911
        match name:
            case "today" | "now":
                return reference_day
            case "coalesce":
                present = _present(arguments)
                return present[0] if present else None
            case "is_null":
                return arguments[0] is None
            case "is_empty":
                return arguments[0] in (None, "", [], {})
            case "eq":
                return arguments[0] == arguments[1]
            case "lt":
                return arguments[0] < arguments[1]
            case "gt":
                return arguments[0] > arguments[1]
            case "contains":
                container = arguments[0] or []
                return arguments[1] in container
            case "add_days":
                base = _as_date(arguments[0])
                return None if base is None else base + datetime.timedelta(days=arguments[1])
            case "days_between":
                left, right = _as_date(arguments[0]), _as_date(arguments[1])
                return None if left is None or right is None else (left - right).days
            case "min":
                present = _present(arguments)
                return min(present) if present else None
            case "max":
                present = _present(arguments)
                return max(present) if present else None
            case "first":
                value = arguments[0]
                return value[0] if value else None
            case "join":
                separator, values = arguments[0], arguments[1] or []
                return separator.join(str(value) for value in values)
        raise RuleError(f"{name!r} has no implementation.")  # pragma: no cover

    return resolve(expression)
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_rules.py -v && make lint`
Expected: PASS (18 tests), lint clean

- [ ] **Step 5: Commit**

```bash
git add src/edutap/data_provider/rules.py tests/test_rules.py
git commit -m "feat: add the closed rule language"
```

---

### Task 6: Startup validation — rules against fields and kinds

**Files:**
- Create: `src/edutap/data_provider/validation.py`
- Test: `tests/test_validation.py`

**Interfaces:**
- Consumes: `ProviderConfig`, `ConfigError` (Task 4); `parse_rule`, `FUNCTIONS`, `RuleError` (Task 5); `FieldKind` (Task 2).
- Produces:
  - `validate_config(config: ProviderConfig) -> None` — raises `ConfigError` listing every problem found
  - `referenced_fields(config: ProviderConfig, view_type: str) -> set[str]` — declared plus rule inputs; this is the producer's contract
  - `datetime_fields(config: ProviderConfig, view_type: str) -> set[str]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_validation.py
import pytest

from edutap.data_provider.config import ConfigError, load_config
from edutap.data_provider.validation import (
    datetime_fields,
    referenced_fields,
    validate_config,
)

GOOD = """
constants:
  open_ended: 9999-12-31
views:
  mensapass:
    fields:
      display_name: [STRING, TEXT]
      student_role_valid_until: [STRING, DATETIME]
    derived:
      pass_valid_until:
        kinds: [STRING, DATETIME]
        rule: min(add_days(today(), 7), coalesce(student_role_valid_until, open_ended))
"""


def write(tmp_path, text):
    path = tmp_path / "views.yaml"
    path.write_text(text)
    return path


def test_a_valid_configuration_passes(tmp_path):
    validate_config(load_config(write(tmp_path, GOOD)))


def test_referenced_fields_are_the_producers_contract(tmp_path):
    config = load_config(write(tmp_path, GOOD))
    assert referenced_fields(config, "mensapass") == {
        "display_name",
        "student_role_valid_until",
    }


def test_datetime_fields_are_collected_for_parsing(tmp_path):
    config = load_config(write(tmp_path, GOOD))
    assert datetime_fields(config, "mensapass") == {
        "student_role_valid_until",
        "pass_valid_until",
    }


def test_a_rule_referencing_an_undeclared_field_is_fatal(tmp_path):
    text = GOOD.replace("student_role_valid_until, open_ended", "unknown_field, open_ended")
    with pytest.raises(ConfigError, match="unknown_field"):
        validate_config(load_config(write(tmp_path, text)))


def test_a_date_function_on_a_non_datetime_field_is_fatal(tmp_path):
    text = GOOD.replace("add_days(today(), 7)", "add_days(display_name, 7)")
    with pytest.raises(ConfigError, match="display_name"):
        validate_config(load_config(write(tmp_path, text)))


def test_an_unknown_function_surfaces_as_a_config_error(tmp_path):
    text = GOOD.replace("add_days(today(), 7)", "magic(today())")
    with pytest.raises(ConfigError, match="magic"):
        validate_config(load_config(write(tmp_path, text)))


def test_all_problems_are_reported_together(tmp_path):
    text = GOOD.replace(
        "min(add_days(today(), 7), coalesce(student_role_valid_until, open_ended))",
        "min(add_days(display_name, 7), coalesce(ghost, open_ended))",
    )
    with pytest.raises(ConfigError) as error:
        validate_config(load_config(write(tmp_path, text)))
    assert "display_name" in str(error.value)
    assert "ghost" in str(error.value)


def test_a_rule_may_reference_a_constant(tmp_path):
    validate_config(load_config(write(tmp_path, GOOD)))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_validation.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'edutap.data_provider.validation'`

- [ ] **Step 3: Write the implementation**

```python
# src/edutap/data_provider/validation.py
"""Cross-validation of rules against the fields and kinds they use.

Everything here is fatal at startup. A rule that reads a field which no producer
writes, or does date arithmetic on a field that is not a date, is a defect that must
surface before the service accepts a request — not as a silent wrong validity on an
issued pass.
"""

import ast

from .config import ConfigError
from .config import ProviderConfig
from .rules import FUNCTIONS
from .rules import RuleError
from .rules import parse_rule
from .vocabulary import FieldKind


def _rule_names(tree: ast.Expression) -> set[str]:
    """Return the field or constant names a rule reads."""
    return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} - set(FUNCTIONS)


def referenced_fields(config: ProviderConfig, view_type: str) -> set[str]:
    """Return every field a producer must write for this view.

    Declared fields plus the inputs of every rule, minus named constants and the
    derived names the rules themselves produce.
    """
    view = config.views[view_type]
    names = set(view.fields)
    for derived in view.derived.values():
        names |= _rule_names(parse_rule(derived.rule))
    return names - set(config.constants) - set(view.derived)


def datetime_fields(config: ProviderConfig, view_type: str) -> set[str]:
    """Return the fields of this view that declare DATETIME."""
    view = config.views[view_type]
    stored = {name for name, spec in view.fields.items() if FieldKind.DATETIME in spec.kinds}
    computed = {name for name, spec in view.derived.items() if FieldKind.DATETIME in spec.kinds}
    return stored | computed


def _check_view(config: ProviderConfig, view_type: str) -> list[str]:
    view = config.views[view_type]
    known = set(view.fields) | set(view.derived) | set(config.constants)
    date_like = datetime_fields(config, view_type) | set(config.constants)
    problems: list[str] = []

    for name, derived in view.derived.items():
        try:
            tree = parse_rule(derived.rule)
        except RuleError as error:
            problems.append(f"{view_type}.{name}: {error}")
            continue

        for referenced in sorted(_rule_names(tree) - known):
            problems.append(
                f"{view_type}.{name}: rule reads {referenced!r}, which is neither a declared "
                "field nor a constant — no producer would know to write it."
            )

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            signature = FUNCTIONS[node.func.id]
            for position in signature.date_arguments:
                if position >= len(node.args):
                    continue
                argument = node.args[position]
                if isinstance(argument, ast.Name) and argument.id not in date_like:
                    problems.append(
                        f"{view_type}.{name}: {node.func.id}() needs a date, but "
                        f"{argument.id!r} does not declare DATETIME."
                    )
    return problems


def validate_config(config: ProviderConfig) -> None:
    """Raise :class:`ConfigError` listing every problem across all views."""
    problems: list[str] = []
    for view_type in config.views:
        problems.extend(_check_view(config, view_type))
    if problems:
        raise ConfigError("Invalid view configuration:\n  " + "\n  ".join(problems))
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_validation.py -v && make lint`
Expected: PASS (8 tests), lint clean

- [ ] **Step 5: Commit**

```bash
git add src/edutap/data_provider/validation.py tests/test_validation.py
git commit -m "feat: validate rules against the fields and kinds they use"
```

---

### Task 7: The catalogue

**Files:**
- Create: `src/edutap/data_provider/catalogue.py`
- Test: `tests/test_catalogue.py`

**Interfaces:**
- Consumes: `ProviderConfig` (Task 4), `FieldKind` (Task 2).
- Produces:
  - `CatalogueEntry(BaseModel)` with `key: str`, `kinds: list[FieldKind]`, `derived: bool`, `description: str | None`
  - `catalogue_for(config: ProviderConfig, view_type: str) -> list[CatalogueEntry]` — sorted by key, raises `UnknownViewType`
  - `UnknownViewType(Exception)`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_catalogue.py
import pytest

from edutap.data_provider.catalogue import UnknownViewType, catalogue_for
from edutap.data_provider.config import load_config

CONFIG = """
views:
  mensapass:
    fields:
      display_name:
        kinds: [STRING, TEXT]
        description: Name as printed
      student_role_valid_until: [STRING, DATETIME]
    derived:
      pass_valid_until:
        kinds: [STRING, DATETIME]
        rule: add_days(today(), 7)
"""


def config(tmp_path):
    path = tmp_path / "views.yaml"
    path.write_text(CONFIG)
    return load_config(path)


def test_lists_stored_and_derived_fields_together(tmp_path):
    entries = catalogue_for(config(tmp_path), "mensapass")
    assert [entry.key for entry in entries] == [
        "display_name",
        "pass_valid_until",
        "student_role_valid_until",
    ]


def test_marks_which_fields_are_derived(tmp_path):
    entries = {entry.key: entry for entry in catalogue_for(config(tmp_path), "mensapass")}
    assert entries["pass_valid_until"].derived is True
    assert entries["display_name"].derived is False


def test_carries_kinds_and_description(tmp_path):
    entries = {entry.key: entry for entry in catalogue_for(config(tmp_path), "mensapass")}
    assert entries["display_name"].description == "Name as printed"
    assert "DATETIME" in entries["pass_valid_until"].kinds


def test_an_unknown_view_type_is_an_error(tmp_path):
    with pytest.raises(UnknownViewType, match="esc"):
        catalogue_for(config(tmp_path), "esc")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_catalogue.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'edutap.data_provider.catalogue'`

- [ ] **Step 3: Write the implementation**

```python
# src/edutap/data_provider/catalogue.py
"""The exposed field list of a view.

Derived fields stand here as equals: a consumer sees them without needing to know
they come into being at read time. Fields a row carries but the configuration never
mentions are absent — they are raw material for rules, not output.
"""

from pydantic import BaseModel

from .config import ProviderConfig
from .vocabulary import FieldKind


class UnknownViewType(Exception):
    """The requested view type is not configured."""


class CatalogueEntry(BaseModel):
    """One field a consumer of this view may ask for."""

    key: str
    kinds: list[FieldKind]
    derived: bool
    description: str | None = None


def catalogue_for(config: ProviderConfig, view_type: str) -> list[CatalogueEntry]:
    """Return the catalogue of one view, sorted by key."""
    if view_type not in config.views:
        raise UnknownViewType(
            f"View type {view_type!r} is not configured. Known: "
            f"{', '.join(sorted(config.views)) or '(none)'}."
        )
    view = config.views[view_type]
    entries = [
        CatalogueEntry(key=key, kinds=spec.kinds, derived=False, description=spec.description)
        for key, spec in view.fields.items()
    ]
    entries += [
        CatalogueEntry(key=key, kinds=spec.kinds, derived=True, description=spec.description)
        for key, spec in view.derived.items()
    ]
    return sorted(entries, key=lambda entry: entry.key)
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_catalogue.py -v && make lint`
Expected: PASS (4 tests), lint clean

- [ ] **Step 5: Commit**

```bash
git add src/edutap/data_provider/catalogue.py tests/test_catalogue.py
git commit -m "feat: build the catalogue of a view from its configuration"
```

---

### Task 8: Settings and the repository

**Files:**
- Create: `src/edutap/data_provider/settings.py`, `src/edutap/data_provider/repository.py`
- Create: `tests/conftest.py`
- Test: `tests/test_settings.py`, `tests/test_repository.py`

**Interfaces:**
- Consumes: `PersonView`, `PassState` (Task 3).
- Produces:
  - `Settings` with `database_url: str`, `config_path: Path`, `api_token: SecretStr`, `echo_sql: bool = False`; env prefix `EDUTAP_DATA_PROVIDER_`
  - `get_settings() -> Settings` (cached)
  - `Repository(session_factory)` with `async def person_view(person_uid: str, view_type: str) -> dict[str, Any] | None`

**Why there is no `pass_states()` method:** the API exposes `/catalogue` and
`/lookup` and nothing else. `pass_state` is read through the **SQL profile** by
`lmu_edutap_backend`, `lmu_edutap_admin_backend`, the callback handlers and the
scheduled tasks. This package owns the table's schema; a reader method with no
caller would be dead code that later invites an endpoint the contract does not have.

- [ ] **Step 1: Write the settings test**

```python
# tests/test_settings.py
import pytest

from edutap.data_provider.settings import Settings


def test_reads_the_prefixed_variables(monkeypatch):
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_CONFIG_PATH", "/etc/views.yaml")
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_API_TOKEN", "secret")
    settings = Settings()
    assert settings.database_url.endswith("/db")
    assert str(settings.config_path) == "/etc/views.yaml"


def test_the_token_is_not_leaked_by_repr(monkeypatch):
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_CONFIG_PATH", "/etc/views.yaml")
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_API_TOKEN", "secret")
    assert "secret" not in repr(Settings())


def test_missing_required_settings_fail_loudly(monkeypatch):
    for name in ("DATABASE_URL", "CONFIG_PATH", "API_TOKEN"):
        monkeypatch.delenv(f"EDUTAP_DATA_PROVIDER_{name}", raising=False)
    with pytest.raises(Exception):
        Settings()
```

- [ ] **Step 2: Write the conftest with a hermetic environment and a container**

```python
# tests/conftest.py
"""Shared fixtures."""

import pytest

_ENVIRONMENT = (
    "EDUTAP_DATA_PROVIDER_DATABASE_URL",
    "EDUTAP_DATA_PROVIDER_CONFIG_PATH",
    "EDUTAP_DATA_PROVIDER_API_TOKEN",
    "EDUTAP_DATA_PROVIDER_ECHO_SQL",
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    """Remove ambient settings and drop cached ones between tests.

    `get_settings`, `get_provider_config` and `get_repository` are lru_cached: without
    clearing them a test would silently run against the previous test's environment,
    and the failure would look like a logic bug rather than a fixture bug.
    """
    for name in _ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)

    from edutap.data_provider import settings as settings_module
    from edutap.data_provider.api import dependencies

    settings_module.get_settings.cache_clear()
    dependencies.get_provider_config.cache_clear()
    dependencies.get_repository.cache_clear()
    yield
    settings_module.get_settings.cache_clear()
    dependencies.get_provider_config.cache_clear()
    dependencies.get_repository.cache_clear()


@pytest.fixture(scope="session")
def postgres_url():
    """Start a PostgreSQL container and return an asyncpg URL for it."""
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:18-alpine", driver="asyncpg") as container:
        yield container.get_connection_url()


@pytest.fixture
async def engine(postgres_url):
    """An engine on a fresh schema with this package's tables created."""
    from sqlalchemy.ext.asyncio import create_async_engine

    from edutap.data_provider.models.base import metadata
    from edutap.data_provider.models import db  # noqa: F401  registers the tables

    engine = create_async_engine(postgres_url)
    async with engine.begin() as connection:
        await connection.run_sync(metadata.drop_all)
        await connection.run_sync(metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(engine):
    """A session factory bound to the test engine."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    return async_sessionmaker(engine, expire_on_commit=False)
```

Note: `metadata.create_all` appears **only in tests**. The service never creates a
table; in a deployment the schema comes from `edutap-dbdef`.

- [ ] **Step 3: Write the repository test**

```python
# tests/test_repository.py
import pytest
from sqlalchemy import text

from edutap.data_provider.repository import Repository

pytestmark = pytest.mark.integration


async def insert_view(session_factory, person_uid, view_type, data):
    async with session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO person_view (person_uid, view_type, data) "
                "VALUES (:uid, :view, :data::jsonb)"
            ),
            {"uid": person_uid, "view": view_type, "data": data},
        )
        await session.commit()


async def test_reads_the_payload_of_one_view(session_factory):
    await insert_view(session_factory, "a@lmu.de", "full_view", '{"surname": "Doe"}')
    repository = Repository(session_factory)
    assert await repository.person_view("a@lmu.de", "full_view") == {"surname": "Doe"}


async def test_an_absent_row_is_none(session_factory):
    repository = Repository(session_factory)
    assert await repository.person_view("nobody@lmu.de", "full_view") is None


async def test_view_types_do_not_leak_into_each_other(session_factory):
    await insert_view(session_factory, "a@lmu.de", "full_view", '{"surname": "Doe"}')
    await insert_view(session_factory, "a@lmu.de", "mensapass", '{"display_name": "A. Doe"}')
    repository = Repository(session_factory)
    assert await repository.person_view("a@lmu.de", "mensapass") == {"display_name": "A. Doe"}


async def test_the_pass_state_table_accepts_a_google_style_identifier(session_factory):
    """The schema must hold what a provider actually issues, prefix and all."""
    async with session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO pass_state (pass_id, person_uid, wallet_type, state, pass_template) "
                "VALUES ('3388000000022195611.mensapass-a-lmu-de', 'a@lmu.de', "
                "'GOOGLE_ST', 'ACTIVE', 'mensapass')"
            )
        )
        await session.commit()
        stored = await session.execute(text("SELECT pass_id, pass_template_variant FROM pass_state"))
    assert stored.one() == ("3388000000022195611.mensapass-a-lmu-de", None)


async def test_the_repository_never_writes(session_factory):
    import inspect

    from edutap.data_provider import repository as module

    source = inspect.getsource(module)
    for statement in ("INSERT", "UPDATE ", "DELETE", "session.add", "commit()"):
        assert statement not in source, f"{statement} in a read-only service"
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_settings.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'edutap.data_provider.settings'`

- [ ] **Step 5: Write settings and repository**

```python
# src/edutap/data_provider/settings.py
"""Configuration of the service process."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict


class Settings(BaseSettings):
    """Everything the process needs to start."""

    model_config = SettingsConfigDict(
        env_prefix="EDUTAP_DATA_PROVIDER_",
        env_file=".env",
        extra="ignore",
    )

    database_url: str
    config_path: Path
    api_token: SecretStr
    echo_sql: bool = False


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
```

```python
# src/edutap/data_provider/repository.py
"""Reading the two tables. The only module that talks to a database.

The service is read-only: this module issues SELECT statements and nothing else.
`tests/test_repository.py` asserts that by reading this file's source.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from .models.db import PersonView


class Repository:
    """Reads person views and pass states."""

    def __init__(self, session_factory: async_sessionmaker) -> None:
        """Store the session factory; one session is opened per call."""
        self._session_factory = session_factory

    async def person_view(self, person_uid: str, view_type: str) -> dict[str, Any] | None:
        """Return the payload of one view, or None when the row does not exist."""
        statement = select(PersonView.data).where(
            PersonView.person_uid == person_uid,
            PersonView.view_type == view_type,
        )
        async with self._session_factory() as session:
            result = await session.execute(statement)
            return result.scalar_one_or_none()

    async def pass_states(self, person_uid: str) -> list[PassState]:
        """Return every issued pass of one person."""
        statement = select(PassState).where(PassState.person_uid == person_uid)
        async with self._session_factory() as session:
            result = await session.execute(statement)
            return list(result.scalars().all())
```

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_settings.py -v && .venv/bin/python -m pytest -m integration tests/test_repository.py -v && make lint`
Expected: PASS (3 unit, 5 integration). Docker must be running for the second command.

- [ ] **Step 7: Commit**

```bash
git add src/edutap/data_provider/settings.py src/edutap/data_provider/repository.py tests/conftest.py tests/test_settings.py tests/test_repository.py
git commit -m "feat: add settings and the read-only repository"
```

---

### Task 9: The API — catalogue and lookup

**Files:**
- Create: `src/edutap/data_provider/api/auth.py`, `api/errors.py`, `api/routers.py`, `api/dependencies.py`
- Modify: `src/edutap/data_provider/api/app.py`
- Test: `tests/test_api_catalogue.py`, `tests/test_api_lookup.py`

**Interfaces:**
- Consumes: everything from Tasks 4–8.
- Produces:
  - `GET /catalogue?view_type=…` → `list[CatalogueEntry]`
  - `POST /lookup` with `{person_uid, view_type, fields}` → `dict[str, Any]`
  - `api.dependencies.get_repository`, `get_provider_config` — the seams tests override

- [ ] **Step 1: Write the catalogue test**

```python
# tests/test_api_catalogue.py
import pytest
from fastapi.testclient import TestClient

from edutap.data_provider.api.app import create_app
from edutap.data_provider.api.dependencies import get_provider_config
from edutap.data_provider.config import load_config

CONFIG = """
views:
  mensapass:
    fields:
      display_name: [STRING, TEXT]
    derived:
      pass_valid_until:
        kinds: [STRING, DATETIME]
        rule: add_days(today(), 7)
"""


@pytest.fixture
def client(tmp_path, monkeypatch):
    path = tmp_path / "views.yaml"
    path.write_text(CONFIG)
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_CONFIG_PATH", str(path))
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_API_TOKEN", "test-token")
    app = create_app()
    app.dependency_overrides[get_provider_config] = lambda: load_config(path)
    return TestClient(app)


def test_catalogue_lists_the_fields_of_a_view(client):
    response = client.get(
        "/catalogue", params={"view_type": "mensapass"}, headers={"Authorization": "Bearer test-token"}
    )
    assert response.status_code == 200
    assert [entry["key"] for entry in response.json()] == ["display_name", "pass_valid_until"]
    assert [entry["derived"] for entry in response.json()] == [False, True]


def test_an_unknown_view_type_is_a_problem_document(client):
    response = client.get(
        "/catalogue", params={"view_type": "ghost"}, headers={"Authorization": "Bearer test-token"}
    )
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "ghost" in response.json()["detail"]


def test_without_a_token_the_catalogue_is_closed(client):
    assert client.get("/catalogue", params={"view_type": "mensapass"}).status_code == 401


def test_a_wrong_token_is_rejected(client):
    response = client.get(
        "/catalogue", params={"view_type": "mensapass"}, headers={"Authorization": "Bearer nope"}
    )
    assert response.status_code == 401
```

- [ ] **Step 2: Write the lookup test**

```python
# tests/test_api_lookup.py
import datetime

import pytest
from fastapi.testclient import TestClient

from edutap.data_provider.api.app import create_app
from edutap.data_provider.api.dependencies import get_provider_config, get_repository
from edutap.data_provider.config import load_config

CONFIG = """
constants:
  open_ended: 9999-12-31
views:
  mensapass:
    fields:
      display_name: [STRING, TEXT]
      student_role_valid_until: [STRING, DATETIME]
    derived:
      pass_valid_until:
        kinds: [STRING, DATETIME]
        rule: min(add_days(today(), 7), coalesce(student_role_valid_until, open_ended))
"""

ROW = {
    "display_name": "A. Doe",
    "student_role_valid_until": "2026-08-02",
    "internal_note": "not in the catalogue",
}


class FakeRepository:
    def __init__(self, row):
        self._row = row

    async def person_view(self, person_uid, view_type):
        return self._row if person_uid == "a@lmu.de" else None


@pytest.fixture
def client(tmp_path, monkeypatch):
    path = tmp_path / "views.yaml"
    path.write_text(CONFIG)
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_CONFIG_PATH", str(path))
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_API_TOKEN", "test-token")
    app = create_app()
    app.dependency_overrides[get_provider_config] = lambda: load_config(path)
    app.dependency_overrides[get_repository] = lambda: FakeRepository(ROW)
    return TestClient(app)


def post(client, body):
    return client.post("/lookup", json=body, headers={"Authorization": "Bearer test-token"})


def test_returns_exactly_the_requested_fields(client):
    response = post(
        client,
        {"person_uid": "a@lmu.de", "view_type": "mensapass", "fields": ["display_name"]},
    )
    assert response.status_code == 200
    assert response.json() == {"display_name": "A. Doe"}


def test_a_derived_field_is_computed_at_read_time(client):
    response = post(
        client,
        {"person_uid": "a@lmu.de", "view_type": "mensapass", "fields": ["pass_valid_until"]},
    )
    assert response.json()["pass_valid_until"] == "2026-08-02"


def test_fields_outside_the_catalogue_are_an_error(client):
    response = post(
        client,
        {"person_uid": "a@lmu.de", "view_type": "mensapass", "fields": ["internal_note"]},
    )
    assert response.status_code == 400
    assert "internal_note" in response.json()["detail"]


def test_an_unknown_person_is_a_not_found_problem(client):
    response = post(
        client,
        {"person_uid": "nobody@lmu.de", "view_type": "mensapass", "fields": ["display_name"]},
    )
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")


def test_an_empty_field_is_absent_rather_than_null(client):
    response = post(
        client,
        {
            "person_uid": "a@lmu.de",
            "view_type": "mensapass",
            "fields": ["display_name", "student_role_valid_until"],
        },
    )
    assert set(response.json()) == {"display_name", "student_role_valid_until"}
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_api_catalogue.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'edutap.data_provider.api.dependencies'`

- [ ] **Step 4: Write auth, errors and dependencies**

```python
# src/edutap/data_provider/api/errors.py
"""Errors as application/problem+json."""

from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import JSONResponse


class ProblemError(Exception):
    """An error that becomes a problem document."""

    def __init__(self, status_code: int, title: str, detail: str) -> None:
        """Record the three parts of the document."""
        super().__init__(detail)
        self.status_code = status_code
        self.title = title
        self.detail = detail


def install_error_handlers(app: FastAPI) -> None:
    """Render ProblemError as application/problem+json."""

    @app.exception_handler(ProblemError)
    async def _handle(_: Request, error: ProblemError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            media_type="application/problem+json",
            content={"title": error.title, "status": error.status_code, "detail": error.detail},
        )
```

```python
# src/edutap/data_provider/api/auth.py
"""Bearer authentication."""

from fastapi import Depends
from fastapi import Header

from ..settings import Settings
from ..settings import get_settings
from .errors import ProblemError


async def require_token(
    authorization: str = Header(default=""),
    settings: Settings = Depends(get_settings),
) -> None:
    """Reject anything but the configured bearer token."""
    expected = f"Bearer {settings.api_token.get_secret_value()}"
    if authorization != expected:
        raise ProblemError(401, "Unauthorized", "A valid bearer token is required.")
```

```python
# src/edutap/data_provider/api/dependencies.py
"""Wiring. Tests override these two seams."""

from functools import lru_cache

from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine

from ..config import ProviderConfig
from ..config import load_config
from ..repository import Repository
from ..settings import get_settings
from ..validation import validate_config


@lru_cache
def get_provider_config() -> ProviderConfig:
    """Load and validate the view configuration once per process."""
    config = load_config(get_settings().config_path)
    validate_config(config)
    return config


@lru_cache
def get_repository() -> Repository:
    """Build the repository against the configured database."""
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=settings.echo_sql)
    return Repository(async_sessionmaker(engine, expire_on_commit=False))
```

- [ ] **Step 5: Write the routers**

```python
# src/edutap/data_provider/api/routers.py
"""The two endpoints of the contract."""

from typing import Any

from fastapi import APIRouter
from fastapi import Depends
from pydantic import BaseModel

from ..catalogue import CatalogueEntry
from ..catalogue import UnknownViewType
from ..catalogue import catalogue_for
from ..config import ProviderConfig
from ..repository import Repository
from ..rules import evaluate
from ..rules import parse_rule
from ..validation import datetime_fields
from .auth import require_token
from .dependencies import get_provider_config
from .dependencies import get_repository
from .errors import ProblemError


router = APIRouter(dependencies=[Depends(require_token)])


class LookupRequest(BaseModel):
    """What a consumer asks for."""

    person_uid: str
    view_type: str
    fields: list[str]


@router.get("/catalogue", response_model=list[CatalogueEntry])
async def catalogue(
    view_type: str,
    config: ProviderConfig = Depends(get_provider_config),
) -> list[CatalogueEntry]:
    """Return the field list of one view."""
    try:
        return catalogue_for(config, view_type)
    except UnknownViewType as error:
        raise ProblemError(404, "Unknown view type", str(error)) from error


@router.post("/lookup")
async def lookup(
    request: LookupRequest,
    config: ProviderConfig = Depends(get_provider_config),
    repository: Repository = Depends(get_repository),
) -> dict[str, Any]:
    """Return exactly the requested fields for one person."""
    try:
        entries = {entry.key: entry for entry in catalogue_for(config, request.view_type)}
    except UnknownViewType as error:
        raise ProblemError(404, "Unknown view type", str(error)) from error

    unknown = sorted(set(request.fields) - set(entries))
    if unknown:
        raise ProblemError(
            400,
            "Unknown field",
            f"View {request.view_type!r} does not offer: {', '.join(unknown)}.",
        )

    payload = await repository.person_view(request.person_uid, request.view_type)
    if payload is None:
        raise ProblemError(
            404, "Unknown person", f"No {request.view_type!r} view for this person."
        )

    view = config.views[request.view_type]
    dates = datetime_fields(config, request.view_type)
    answer: dict[str, Any] = {}
    for key in request.fields:
        if entries[key].derived:
            value = evaluate(
                parse_rule(view.derived[key].rule), payload, config.constants, dates
            )
        else:
            value = payload.get(key)
        if value is not None:
            answer[key] = value.isoformat() if hasattr(value, "isoformat") else value
    return answer
```

- [ ] **Step 6: Wire the app**

```python
# src/edutap/data_provider/api/app.py — replace the module with this
"""Application factory."""

from fastapi import APIRouter
from fastapi import FastAPI

from .errors import install_error_handlers
from .routers import router


health_router = APIRouter()


@health_router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Report that the process is up."""
    return {"status": "ok"}


def create_app() -> FastAPI:
    """Build the FastAPI application."""
    app = FastAPI(title="eduTAP data provider", version="0.1.0")
    install_error_handlers(app)
    app.include_router(health_router)
    app.include_router(router)
    return app
```

- [ ] **Step 7: Run the tests**

Run: `.venv/bin/python -m pytest -v && make lint`
Expected: PASS (all unit tests including the nine new API tests), lint clean

- [ ] **Step 8: Commit**

```bash
git add src/edutap/data_provider/api tests/test_api_catalogue.py tests/test_api_lookup.py
git commit -m "feat: add the catalogue and lookup endpoints"
```

---

### Task 10: Docker environment, documentation, release readiness

**Files:**
- Create: `Dockerfile`, `compose.yml`, `views.example.yaml`, `.env.example`
- Create: `docs/index.md`, `docs/tutorial.md`, `docs/how-to.md`, `docs/reference.md`, `docs/explanation.md`, `docs/conf.py`
- Create: `CHANGES.md`
- Modify: `README.md`
- Test: `tests/test_docs.py`

**Interfaces:**
- Consumes: everything.
- Produces: a runnable compose environment and a documentation set that matches the implementation.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_docs.py
import pathlib
import re

ROOT = pathlib.Path(__file__).parent.parent
DOCS = ROOT / "docs"


def test_every_endpoint_is_documented():
    reference = (DOCS / "reference.md").read_text()
    for endpoint in ("/catalogue", "/lookup", "/healthz"):
        assert endpoint in reference


def test_every_rule_function_is_documented():
    from edutap.data_provider.rules import FUNCTIONS

    reference = (DOCS / "reference.md").read_text()
    for name in FUNCTIONS:
        assert f"`{name}(" in reference or f"`{name}`" in reference, f"{name} undocumented"


def test_every_setting_is_documented():
    from edutap.data_provider.settings import Settings

    reference = (DOCS / "reference.md").read_text()
    for field in Settings.model_fields:
        assert f"EDUTAP_DATA_PROVIDER_{field.upper()}" in reference


def test_the_example_configuration_is_valid():
    from edutap.data_provider.config import load_config
    from edutap.data_provider.validation import validate_config

    validate_config(load_config(ROOT / "views.example.yaml"))


def test_readme_mentions_no_endpoint_that_does_not_exist():
    from edutap.data_provider.api.app import create_app

    paths = {route.path for route in create_app().routes}
    readme = (ROOT / "README.md").read_text()
    for mentioned in set(re.findall(r"`(/[a-z]+)`", readme)):
        assert mentioned in paths, f"{mentioned} in README but not a route"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_docs.py -v`
Expected: FAIL — `docs/reference.md` does not exist

- [ ] **Step 3: Write the example configuration**

```yaml
# views.example.yaml
constants:
  # LMU writes an unlimited role as this date rather than as a missing value.
  # Another site may use a different sentinel — it is configuration, not a constant
  # of the package.
  open_ended: 9999-12-31

views:
  full_view:
    description: Complete person record as the producer writes it
    fields:
      eduperson_principal_name: [STRING, TEXT, NFC]
      given_name: [STRING, TEXT]
      surname: [STRING, TEXT]
      mail: [STRING, TEXT, LINK]
      eduperson_affiliation: [STRING, TEXT]

  mensapass:
    description: What the canteen pass needs
    fields:
      eduperson_principal_name: [STRING, TEXT, NFC]
      display_name: [STRING, TEXT]
      student_role_valid_until: [STRING, DATETIME]
      employee_role_valid_until: [STRING, DATETIME]
    derived:
      pass_valid_until:
        kinds: [STRING, TEXT, DATETIME]
        description: At most seven days ahead, never past the role that carries it
        rule: >
          min(add_days(today(), 7),
              coalesce(student_role_valid_until, open_ended),
              coalesce(employee_role_valid_until, open_ended))
```

- [ ] **Step 4: Write the Docker test environment**

```dockerfile
# Dockerfile
FROM python:3.14-slim AS build
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml README.md ./
COPY src ./src
RUN uv pip install --system --no-cache .

FROM python:3.14-slim
RUN useradd --create-home --uid 10001 app
COPY --from=build /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY --from=build /usr/local/bin /usr/local/bin
WORKDIR /app
USER app
EXPOSE 8000
CMD ["uvicorn", "edutap.data_provider.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
```

```yaml
# compose.yml
services:
  db:
    image: postgres:18-alpine
    environment:
      POSTGRES_USER: data_provider
      POSTGRES_PASSWORD: data_provider
      POSTGRES_DB: data_provider
    ports: ["5432:5432"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U data_provider"]
      interval: 5s
      retries: 10

  app:
    build: .
    depends_on:
      db: { condition: service_healthy }
    environment:
      EDUTAP_DATA_PROVIDER_DATABASE_URL: postgresql+asyncpg://data_provider:data_provider@db/data_provider
      EDUTAP_DATA_PROVIDER_CONFIG_PATH: /app/views.yaml
      EDUTAP_DATA_PROVIDER_API_TOKEN: ${EDUTAP_DATA_PROVIDER_API_TOKEN:-dev-token}
    volumes:
      - ./views.example.yaml:/app/views.yaml:ro
    ports: ["8000:8000"]
```

`.env.example` carries `EDUTAP_DATA_PROVIDER_API_TOKEN=dev-token` and a comment that
the schema is applied with `edutap-dbdef`, not by this service.

- [ ] **Step 5: Write the documentation**

`docs/index.md` — one paragraph plus a toctree over the four pages.

`docs/tutorial.md` — from an empty checkout to a first answered lookup: `make venv`,
start the compose environment, apply the schema with
`edutap-dbdef create --out schema.sql` and `edutap-dbdef apply schema.sql`, insert one
row with `psql`, then `curl` the catalogue and the lookup and see the derived
`pass_valid_until`.

`docs/how-to.md` — three how-tos: *add a view type* (declare fields and kinds, what
the producer must then write, why the referenced fields are the contract); *write a
derivation rule* (the function table, the seven-day example, why `9999-12-31` is a
constant rather than a special case); *let a SQL consumer read directly* (the raw
rows, no derivation, and that the consumer brings its own post-processing — HEIDI's
`field_map` as the example).

`docs/reference.md` — the two endpoints with request and response shapes, `/healthz`,
every environment variable `EDUTAP_DATA_PROVIDER_*`, the configuration file format,
the complete rule function table, the field kinds, and the two tables with their
columns.

`docs/explanation.md` — why the service is read-only and who writes instead; why the
API is mandatory and the SQL profile optional; why derivation runs at read time; why
field names are standard-native and flat; why the vocabulary is copied rather than
imported.

`docs/conf.py`:

```python
"""Sphinx configuration."""

project = "edutap.data_provider"
extensions = ["myst_parser"]
myst_enable_extensions = ["colon_fence", "deflist"]
exclude_patterns = ["_build", "superpowers"]
html_theme = "alabaster"
```

- [ ] **Step 6: Update README and CHANGES**

`README.md`: what the service is, the "read-only, someone else writes" sentence, the
two contract surfaces, install and run, a pointer to `docs/`. Replace the "Status:
planned" line.

```markdown
# CHANGES.md
# Changelog

## 0.1.0 (unreleased)

- Initial release: `GET /catalogue` and `POST /lookup` over configured views, with
  read-time derivation from a closed rule language.
```

- [ ] **Step 7: Build the docs and run everything**

Run: `uv pip install -e ".[docs]" && .venv/bin/python -m sphinx -E -W docs docs/_build/html && make lint && make test-local && make test-integration`
Expected: docs build without warnings, all suites green

- [ ] **Step 8: Commit**

```bash
git add Dockerfile compose.yml views.example.yaml .env.example docs CHANGES.md README.md tests/test_docs.py
git commit -m "docs: add the Docker environment and the documentation"
```

---

## Verification checklist

- [ ] `make lint` clean (ruff check, ruff format, ty)
- [ ] `make test-local` green without Docker
- [ ] `make test-integration` green with Docker
- [ ] `uv run tox` green over 3.12, 3.13, 3.14
- [ ] `sphinx-build -W` builds without warnings
- [ ] No `INSERT`, `UPDATE`, `DELETE` or `create_all` anywhere in `src/`
- [ ] `edutap-dbdef create --packages edutap.data_provider` renders both tables
- [ ] `docker compose up` answers `/healthz`, `/catalogue` and `/lookup`

## Follow-up work (separate plans)

1. **`edutap.pass_builder` client change** — `view_type` on `/lookup` and
   `/catalogue`, the `data_field` cache and `/fields` endpoint carrying the
   dimension, and `value_type` giving way to `kinds` in the publish check.
2. **`lmu_edutap_data_vzd_webhook`** — the LMU producer, including the full initial
   load that an event-driven updater cannot provide.
3. **The LMU compatibility view** `heidi_full_view` over `person_view`, in the
   deployment repository.
4. **Vocabulary alignment** in `edutap.pass_builder`, `edutap.heidi_api` and
   wherever `full_view`'s literals are still used.
