from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from edutap.data_provider.models.base import NAMING_CONVENTION, metadata
from edutap.data_provider.models.db import PassState, PersonView


def test_tables_live_on_the_package_metadata_only():
    from sqlmodel import SQLModel

    # `pass_instance` joins this set in task 4 of the schema-split plan; until then
    # its absence is the correct, current state, not a gap to "complete".
    assert set(metadata.tables) == {
        "public.person_view",
        "public.pass_state",
    }
    assert "public.person_view" not in SQLModel.metadata.tables


def test_contract_tables_declare_the_public_schema_explicitly():
    """Without the declaration the target schema depends on `search_path`.

    Measured 2026-08-09: with role `edutap` and a schema of the same name the
    tables landed in `edutap` locally, while production resolved to `public` —
    two deployments of one package with different layouts. Declaring the schema
    removes the ambiguity.
    """
    # `pass_instance` joins this tuple in task 4 of the schema-split plan; until
    # then its absence is the correct, current state, not a gap to "complete".
    for name in ("person_view", "pass_state"):
        assert metadata.tables[f"public.{name}"].schema == "public"


def test_person_view_carries_a_photo_reference():
    """JSONB, not bytea: the source stays open — `s3_key`, `url` or `base64`.

    A consumer then fetches the image itself instead of it being carried through
    every query.
    """
    column = metadata.tables["public.person_view"].columns["photo"]
    assert isinstance(column.type, JSONB)
    assert column.nullable


def test_naming_convention_is_the_canonical_one():
    assert dict(metadata.naming_convention) == NAMING_CONVENTION


def test_person_view_has_a_composite_primary_key():
    table = metadata.tables["public.person_view"]
    assert [column.name for column in table.primary_key.columns] == ["person_uid", "view_type"]


def test_person_view_keys_use_byte_collation():
    table = metadata.tables["public.person_view"]
    for name in ("person_uid", "view_type"):
        assert table.columns[name].type.collation == "C"


def test_person_view_indexes_view_type_for_whole_view_reads():
    table = metadata.tables["public.person_view"]
    indexed = {tuple(column.name for column in index.columns) for index in table.indexes}
    assert ("view_type",) in indexed


def test_pass_state_identifier_is_a_string_not_a_uuid():
    """Usually a UUID, but Google object identifiers carry a prefix and suffix."""
    column = metadata.tables["public.pass_state"].columns["pass_id"]
    assert isinstance(column.type, sa.String)
    assert column.type.length == 255
    assert column.primary_key


def test_pass_state_separates_issuance_from_holder():
    table = metadata.tables["public.pass_state"]
    assert "issuance_state" in table.columns
    assert "holder_state" in table.columns
    assert "state" not in table.columns


def test_pass_state_counts_a_version():
    """The counter the instances are compared against via synced_version."""
    column = metadata.tables["public.pass_state"].columns["version"]
    assert isinstance(column.type, sa.Integer)
    assert not column.nullable


def test_pass_state_carries_the_watermark():
    """The event carries the state here, so the event time is the right measure.

    The upsert writes only when edutap-occurred-at is younger than last_event_at;
    a late event then hits zero rows instead of overwriting a newer state.
    """
    column = metadata.tables["public.pass_state"].columns["last_event_at"]
    assert isinstance(column.type, sa.DateTime)
    assert column.type.timezone
    assert not column.nullable


def test_pass_state_keeps_the_provider_native_value():
    """If Google later claims something else, this is the only way to settle it."""
    column = metadata.tables["public.pass_state"].columns["provider_raw"]
    assert isinstance(column.type, JSONB)
    assert column.nullable


def test_pass_state_does_not_reference_the_person_view():
    """No foreign key: a pass exists whether or not a view row currently does."""
    table = metadata.tables["public.pass_state"]
    assert table.foreign_keys == set()


def test_pass_state_indexes_the_question_readers_ask():
    table = metadata.tables["public.pass_state"]
    indexed = {tuple(column.name for column in index.columns) for index in table.indexes}
    assert ("person_uid", "pass_template", "wallet_type") in indexed


def test_vocabulary_columns_are_text_not_native_enums():
    table = metadata.tables["public.pass_state"]
    for name in ("wallet_type", "issuance_state", "holder_state"):
        assert isinstance(table.columns[name].type, sa.String)
        assert not isinstance(table.columns[name].type, sa.Enum)


def test_variant_is_optional_because_a_default_exists():
    assert metadata.tables["public.pass_state"].columns["pass_template_variant"].nullable


def test_models_are_usable_as_python_objects():
    view = PersonView(person_uid="x@lmu.de", view_type="full_view", data={"surname": "Doe"})
    assert view.data["surname"] == "Doe"
    state = PassState(
        pass_id="3388000000022195611.abc",
        person_uid="x@lmu.de",
        wallet_type="GOOGLE_ST",
        issuance_state="ISSUED",
        holder_state="NOT_PRESENT",
        pass_template="mensapass",
        last_event_at=datetime.now(UTC),
    )
    assert state.pass_template_variant is None


def test_schema_definition_announces_this_package():
    import pytest

    pytest.importorskip("edutap.db_definitions")
    from edutap.data_provider.models.dbdef import definition

    assert definition.name == "edutap.data_provider"
    assert definition.metadata is metadata
    assert definition.version_table == "alembic_version_data_provider"
    assert sorted(definition.table_names) == ["public.pass_state", "public.person_view"]


def test_entry_point_resolves_to_the_definition():
    import pytest

    pytest.importorskip("edutap.db_definitions")
    from importlib.metadata import entry_points

    from edutap.data_provider.models.dbdef import definition

    points = [p for p in entry_points(group="edutap.db_definitions") if p.name == "schema"]
    assert points, "the edutap.db_definitions entry point is not installed"
    assert points[0].load() is definition


def test_the_python_side_default_is_timezone_aware():
    """`tz=UTC`, not a naive local time.

    Mutation testing found `datetime.now(tz=UTC)` could become `datetime.now(tz=None)`
    unnoticed. Both columns are `timestamptz`, so a naive value would be interpreted
    against the server's time zone -- an `updated_at` silently wrong by the offset of
    whichever machine happened to write the row, and wrong differently per machine.
    """
    from edutap.data_provider.models.db import _utcnow

    now = _utcnow()

    assert now.tzinfo is not None
    assert now.utcoffset() == UTC.utcoffset(None)
