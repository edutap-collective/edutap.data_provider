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


def test_malformed_yaml_is_fatal(tmp_path):
    text = "views:\n  full_view:\n    fields: [unbalanced\n"
    with pytest.raises(ConfigError, match="views.yaml"):
        load_config(write(tmp_path, text))


def test_fields_accept_the_long_mapping_form(tmp_path):
    text = CONFIG.replace(
        "      surname: [STRING, TEXT]",
        "      surname:\n        kinds: [STRING, TEXT]\n        description: Family name",
    )
    config = load_config(write(tmp_path, text))
    surname = config.views["full_view"].fields["surname"]
    assert surname.kinds == [FieldKind.STRING, FieldKind.TEXT]
    assert surname.description == "Family name"
