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
    rule = "if_else(exists(employee_role_valid_until), 'employee', 'other')"
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


def test_the_conditional_is_not_named_if_because_python_reserves_it():
    """`if` cannot be a call target: ast.parse refuses it before any whitelist runs."""
    with pytest.raises(RuleError, match="parse"):
        parse_rule("if(exists(mail), 'a', 'b')")
