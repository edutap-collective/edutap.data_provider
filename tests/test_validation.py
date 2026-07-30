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
