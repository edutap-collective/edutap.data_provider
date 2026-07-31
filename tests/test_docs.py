import pathlib
import re

ROOT = pathlib.Path(__file__).parent.parent
DOCS = ROOT / "docs"


def section_of(text, heading):
    """Return one Markdown section: its heading line and everything under it.

    `heading` is matched as a substring of the heading line, and the section ends at
    the next heading of the same or a higher level. Asserting against the whole file
    passes as soon as a name appears *anywhere* in it — under the wrong table, in an
    unrelated example — which is exactly the drift these tests exist to catch.
    """
    lines = text.splitlines()
    for start, line in enumerate(lines):
        if not (line.startswith("#") and heading in line):
            continue
        level = len(line) - len(line.lstrip("#"))
        for end in range(start + 1, len(lines)):
            following = lines[end]
            if following.startswith("#") and len(following) - len(following.lstrip("#")) <= level:
                return "\n".join(lines[start:end])
        return "\n".join(lines[start:])
    raise AssertionError(f"docs/reference.md has no heading containing {heading!r}")


def test_every_endpoint_is_documented(configured_environment):
    """`configured_environment`: `create_app` now resolves both seams while it builds,
    so even a test that only wants the route table needs a configuration that loads.
    """
    from edutap.data_provider.api.app import create_app

    # Derived from the application, never from a list kept here: a hardcoded tuple
    # documents the routes someone remembered, and a new route nobody wrote down
    # would leave this green. The OpenAPI document rather than `app.routes` for the
    # reason given in `test_readme_mentions_no_endpoint_that_does_not_exist`.
    reference = (DOCS / "reference.md").read_text()
    for endpoint in create_app().openapi()["paths"]:
        assert endpoint in reference, f"{endpoint} is a route but is undocumented"


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


def test_every_wallet_type_is_documented():
    from edutap.data_provider.vocabulary import WalletType

    vocabulary = section_of((DOCS / "reference.md").read_text(), "Vocabulary")
    for wallet_type in WalletType:
        assert f"`{wallet_type.value}`" in vocabulary, f"{wallet_type.value} undocumented"


def test_every_pass_lifecycle_state_is_documented():
    from edutap.data_provider.vocabulary import PassLifecycleState

    vocabulary = section_of((DOCS / "reference.md").read_text(), "Vocabulary")
    for state in PassLifecycleState:
        assert f"`{state.value}`" in vocabulary, f"{state.value} undocumented"


def test_every_table_column_is_documented():
    from edutap.data_provider.models.db import PassState, PersonView

    reference = (DOCS / "reference.md").read_text()
    for model in (PersonView, PassState):
        assert f"`{model.__tablename__}`" in reference
        # The table's own section, not the whole page: `person_uid` is a column of
        # both tables, so a page-wide search would accept one table's column list
        # documenting the other's.
        table = section_of(reference, f"`{model.__tablename__}`")
        for column in model.__table__.columns:
            undocumented = f"{model.__tablename__}.{column.name} undocumented"
            assert f"`{column.name}`" in table, undocumented


def test_the_documentation_set_follows_diataxis():
    index = (DOCS / "index.md").read_text()
    for page in ("tutorial", "how-to", "reference", "explanation"):
        assert (DOCS / f"{page}.md").is_file(), f"docs/{page}.md missing"
        assert page in index, f"docs/{page}.md not in the toctree"


def test_the_example_configuration_is_valid():
    from edutap.data_provider.config import load_config
    from edutap.data_provider.validation import validate_config

    validate_config(load_config(ROOT / "views.example.yaml"))


def test_readme_mentions_no_endpoint_that_does_not_exist(configured_environment):
    from edutap.data_provider.api.app import create_app

    # The OpenAPI document, not `app.routes`: since Starlette 1.3 an included router
    # appears in `routes` as an `_IncludedRouter` that has no `.path` at all, so
    # iterating `routes` would raise before it could compare anything.
    paths = set(create_app().openapi()["paths"])
    readme = (ROOT / "README.md").read_text()
    for mentioned in set(re.findall(r"`(/[a-z]+)`", readme)):
        assert mentioned in paths, f"{mentioned} in README but not a route"
