"""The exposed field list of a view."""

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


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "views.yaml"
    path.write_text(CONFIG)
    return load_config(path)


def test_lists_stored_and_derived_fields_together(config):
    entries = catalogue_for(config, "mensapass")
    assert [entry.key for entry in entries] == [
        "display_name",
        "pass_valid_until",
        "student_role_valid_until",
    ]


def test_marks_which_fields_are_derived(config):
    entries = {entry.key: entry for entry in catalogue_for(config, "mensapass")}
    assert entries["pass_valid_until"].derived is True
    assert entries["display_name"].derived is False


def test_carries_kinds_and_description(config):
    entries = {entry.key: entry for entry in catalogue_for(config, "mensapass")}
    assert entries["display_name"].description == "Name as printed"
    assert "DATETIME" in entries["pass_valid_until"].kinds


def test_an_unknown_view_type_is_an_error(config):
    with pytest.raises(UnknownViewType, match="esc"):
        catalogue_for(config, "esc")
