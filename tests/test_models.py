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


def test_schema_definition_announces_this_package():
    import pytest

    pytest.importorskip("edutap.db_definitions")
    from edutap.data_provider.models.dbdef import definition

    assert definition.name == "edutap.data_provider"
    assert definition.metadata is metadata
    assert definition.version_table == "alembic_version_data_provider"
    assert sorted(definition.table_names) == ["pass_state", "person_view"]


def test_entry_point_resolves_to_the_definition():
    import pytest

    pytest.importorskip("edutap.db_definitions")
    from importlib.metadata import entry_points

    from edutap.data_provider.models.dbdef import definition

    points = [p for p in entry_points(group="edutap.db_definitions") if p.name == "schema"]
    assert points, "the edutap.db_definitions entry point is not installed"
    assert points[0].load() is definition
