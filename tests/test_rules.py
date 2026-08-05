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


DATETIME_FIELD_SHAPES = pytest.mark.parametrize(
    "raw_value",
    [
        "2026-08-06",
        datetime.date(2026, 8, 6),
        datetime.datetime(2026, 8, 6, 10, 30),
    ],
    ids=["iso_string", "date", "datetime"],
)


@DATETIME_FIELD_SHAPES
def test_a_datetime_field_normalises_to_a_date_regardless_of_its_native_shape(raw_value):
    """A `DATETIME` field may arrive as an ISO string, a date, or a datetime."""
    assert run("student_role_valid_until", {"student_role_valid_until": raw_value}) == (
        datetime.date(2026, 8, 6)
    )


@DATETIME_FIELD_SHAPES
def test_add_days_normalises_every_datetime_field_shape(raw_value):
    payload = {"student_role_valid_until": raw_value}
    assert run("add_days(student_role_valid_until, 1)", payload) == datetime.date(2026, 8, 7)


@DATETIME_FIELD_SHAPES
def test_days_between_normalises_every_datetime_field_shape(raw_value):
    payload = {"student_role_valid_until": raw_value}
    assert run("days_between(student_role_valid_until, today())", payload) == 7


@DATETIME_FIELD_SHAPES
def test_min_normalises_every_datetime_field_shape(raw_value):
    payload = {"student_role_valid_until": raw_value}
    assert run("min(student_role_valid_until, add_days(today(), 30))", payload) == (
        datetime.date(2026, 8, 6)
    )


@DATETIME_FIELD_SHAPES
def test_max_normalises_every_datetime_field_shape(raw_value):
    payload = {"student_role_valid_until": raw_value}
    assert run("max(student_role_valid_until, add_days(today(), 1))", payload) == (
        datetime.date(2026, 8, 6)
    )


def test_a_fixed_arity_function_called_with_too_few_arguments_is_rejected_at_parse_time():
    with pytest.raises(RuleError, match="exists"):
        parse_rule("exists()")


def test_is_null_called_with_too_few_arguments_is_rejected_at_parse_time():
    with pytest.raises(RuleError, match="is_null"):
        parse_rule("is_null()")


def test_if_else_called_with_too_few_arguments_is_rejected_at_parse_time():
    with pytest.raises(RuleError, match="if_else"):
        parse_rule("if_else(1, 2)")


def test_if_else_called_with_too_many_arguments_is_rejected_at_parse_time():
    with pytest.raises(RuleError, match="if_else"):
        parse_rule("if_else(1, 2, 3, 4)")


def test_eq_called_with_too_many_arguments_is_rejected_at_parse_time():
    with pytest.raises(RuleError, match="eq"):
        parse_rule("eq('a', 'a', 'a')")


def test_coalesce_called_with_no_arguments_violates_its_variadic_minimum():
    with pytest.raises(RuleError, match="coalesce"):
        parse_rule("coalesce()")


def test_coalesce_called_with_one_argument_meets_its_variadic_minimum():
    parse_rule("coalesce(a)")


# The comparison functions below are each pinned in BOTH directions, and the reason
# is a measurement rather than thoroughness for its own sake. Mutation testing found
# that every one of them was asserted once, in one direction only: `eq('a', 'a')`
# expecting True was the whole of `eq`, and a single `gt(...)` expecting False was
# the whole of `gt`. Making `eq` return its second argument compared with itself --
# always True -- left all 41 tests in this file green, and so did making `gt` always
# False. For a closed rule language, whose entire premise is that these functions and
# no others exist, an operator that could be inverted unnoticed is the sharpest gap
# the suite had.


def test_eq_answers_in_both_directions():
    assert run("eq('a', 'a')") is True
    assert run("eq('a', 'b')") is False


def test_gt_answers_in_both_directions():
    assert run("gt(2, 1)") is True
    assert run("gt(1, 2)") is False


def test_lt_answers_in_both_directions():
    assert run("lt(1, 2)") is True
    assert run("lt(2, 1)") is False


def test_lt_and_gt_are_strict_at_the_boundary():
    """Equal operands are neither less than nor greater than each other.

    Without this, `<` reading as `<=` -- an off-by-one an author makes without
    noticing -- would change what a pass validity rule decides on its final day
    while every other test stayed green.
    """
    assert run("lt(1, 1)") is False
    assert run("gt(1, 1)") is False


def test_is_empty_reads_its_own_argument():
    """A one-argument function can still read the wrong one.

    `arguments[0]` mutated to `arguments[1]` survived, because no test called
    `is_empty` with a value whose emptiness differed from the value beside it.
    """
    assert run("is_empty(absent)", {}) is True
    assert run("is_empty(present)", {"present": "a value"}) is False
    assert run("is_empty(blank)", {"blank": ""}) is True
    assert run("is_empty(empty_list)", {"empty_list": []}) is True


def test_days_between_needs_both_dates_present():
    """`or`, not `and`: one missing operand is enough to make the answer unknowable.

    With `and`, a single present date would be subtracted from a `None` and raise
    `TypeError` at request time -- the failure class the closed language exists to
    prevent.
    """
    payload = {"start": "2026-07-30", "end": "2026-08-06"}
    assert run("days_between(end, start)", payload) == 7
    assert run("days_between(end, missing)", payload) is None
    assert run("days_between(missing, start)", payload) is None
    assert run("days_between(missing, also_missing)", payload) is None


def test_a_date_is_read_from_exactly_the_first_ten_characters():
    """The slice is `[:10]`, the length of an ISO date, and not a character more.

    A datetime string is truncated to its date; `[:11]` would carry the `T` into
    `date.fromisoformat` and turn a valid stored value into a request-time
    `RuleError`.
    """
    payload = {"student_role_valid_until": "2026-09-30T23:59:59+02:00"}
    assert run("student_role_valid_until", payload) == datetime.date(2026, 9, 30)
