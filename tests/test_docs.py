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


def test_every_field_kind_is_documented():
    from edutap.data_provider.vocabulary import FieldKind

    reference = (DOCS / "reference.md").read_text()
    for kind in FieldKind:
        assert f"`{kind.value}`" in reference, f"{kind.value} undocumented"


def test_every_table_column_is_documented():
    from edutap.data_provider.models.db import PassState, PersonView

    reference = (DOCS / "reference.md").read_text()
    for model in (PersonView, PassState):
        assert f"`{model.__tablename__}`" in reference
        for column in model.__table__.columns:
            undocumented = f"{model.__tablename__}.{column.name} undocumented"
            assert f"`{column.name}`" in reference, undocumented


def test_the_documentation_set_follows_diataxis():
    index = (DOCS / "index.md").read_text()
    for page in ("tutorial", "how-to", "reference", "explanation"):
        assert (DOCS / f"{page}.md").is_file(), f"docs/{page}.md missing"
        assert page in index, f"docs/{page}.md not in the toctree"


def test_the_example_configuration_is_valid():
    from edutap.data_provider.config import load_config
    from edutap.data_provider.validation import validate_config

    validate_config(load_config(ROOT / "views.example.yaml"))


def test_readme_mentions_no_endpoint_that_does_not_exist():
    from edutap.data_provider.api.app import create_app

    # The OpenAPI document, not `app.routes`: since Starlette 1.3 an included router
    # appears in `routes` as an `_IncludedRouter` that has no `.path` at all, so
    # iterating `routes` would raise before it could compare anything.
    paths = set(create_app().openapi()["paths"])
    readme = (ROOT / "README.md").read_text()
    for mentioned in set(re.findall(r"`(/[a-z]+)`", readme)):
        assert mentioned in paths, f"{mentioned} in README but not a route"
