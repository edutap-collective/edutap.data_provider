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


# Regression tests: the date-type check has to see through "any"-returning
# functions (coalesce, min, max, if_else) to what they actually forward,
# instead of only looking at bare field references in a date position.


def test_a_nested_call_in_a_date_position_is_checked_recursively(tmp_path):
    """`add_days(coalesce(a, a), 7)` must be checked through the coalesce.

    Before the recursive check, only bare `ast.Name` arguments were inspected, so
    this nested-call shape passed `validate_config` silently and only failed at
    request time inside `evaluate`, as `RuleError: '...' is not an ISO date.` — the
    exact silent-wrong-validity failure this module exists to prevent at startup.
    """
    text = GOOD.replace(
        "add_days(today(), 7)",
        "add_days(coalesce(display_name, display_name), 7)",
    )
    with pytest.raises(ConfigError, match="display_name"):
        validate_config(load_config(write(tmp_path, text)))


def test_a_nested_call_with_a_non_date_return_type_is_rejected(tmp_path):
    """`days_between` returns a number; feeding that into `add_days` is fatal."""
    text = GOOD.replace(
        "add_days(today(), 7)",
        "add_days(days_between(student_role_valid_until, open_ended), 7)",
    )
    with pytest.raises(ConfigError, match="days_between"):
        validate_config(load_config(write(tmp_path, text)))


def test_the_canonical_seven_day_rule_is_still_accepted(tmp_path):
    """The rule this module's own docstring example is drawn from must still pass:

    `min(add_days(today(), 7), coalesce(student_role_valid_until, open_ended))`
    nests a date-returning call inside `min` and a `DATETIME` field alongside a
    date-like constant inside `coalesce` — both must be recognised as dates.
    """
    validate_config(load_config(write(tmp_path, GOOD)))


def test_if_else_checks_its_branches_but_not_its_condition(tmp_path):
    """`if_else` forwards only its `then`/`else` branches, never its condition.

    The condition here reads `display_name` inside `eq()`, a non-date field used in
    a non-date-requiring position — that must not be flagged. The `else` branch
    also reads `display_name`, but there it stands in for the result of `if_else`,
    which does feed `add_days()` — that must be flagged.
    """
    text = GOOD.replace(
        "min(add_days(today(), 7), coalesce(student_role_valid_until, open_ended))",
        "add_days(if_else(eq(display_name, display_name), student_role_valid_until, "
        "display_name), 7)",
    )
    with pytest.raises(ConfigError) as error:
        validate_config(load_config(write(tmp_path, text)))
    message = str(error.value)
    assert "display_name" in message
    # Exactly one problem: the `else` branch. The condition's use of `display_name`
    # inside `eq()` must not also be reported as a date problem.
    assert message.count("does not declare DATETIME") == 1
