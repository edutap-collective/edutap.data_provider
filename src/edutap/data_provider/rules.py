"""The closed rule language: parsing and evaluation.

A rule is a Python expression restricted to a whitelist of function calls, field
references, named constants and literals. `ast.parse` supplies the tree; the
whitelist is what makes the set closed. There is no `eval` and no user-defined
syntax: anything the whitelist does not name is rejected before evaluation.

Adding a function is a code change with a review — deliberately, so that no small
programming language grows inside a deployment YAML.
"""

import ast
import datetime
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


class RuleError(Exception):
    """A rule is outside the closed language, or cannot be evaluated."""


@dataclass(frozen=True)
class Signature:
    """What a function accepts and returns, for the startup type check.

    `arity` is the exact expected argument count for a fixed-arity function,
    or the minimum count for a `variadic` one (e.g. `coalesce` needs at least
    one argument to mean anything). `parse_rule` enforces it so that a wrong
    argument count is a startup-time `RuleError`, not a request-time
    `IndexError` or `ValueError` from positional unpacking in `evaluate`.

    `date_forward` names, for a function whose `returns` is `"any"`, which
    argument positions it can hand back unchanged — the positions the startup
    date-type check must recurse into to decide whether a nested call like
    `coalesce(a, b)` or `if_else(cond, a, b)` used in a date position actually
    produces a date. A `variadic` `"any"` function (`coalesce`, `min`, `max`)
    forwards all of its actual arguments regardless of count, so it does not
    need `date_forward`; `if_else` is fixed-arity and forwards only its
    `then`/`else` branches, never its condition, so it sets `date_forward`
    explicitly. This lives here, next to `date_arguments`, so the validator
    reads it off `FUNCTIONS` instead of hand-coding a second table that could
    drift from this one.
    """

    name: str
    returns: str  # "date" | "number" | "boolean" | "string" | "any"
    arity: int
    date_arguments: tuple[int, ...] = ()  # positions that must be dates
    variadic: bool = False
    date_forward: tuple[int, ...] = ()  # "any"-returning: positions forwarded verbatim


FUNCTIONS: dict[str, Signature] = {
    "today": Signature("today", "date", 0),
    "now": Signature("now", "date", 0),
    "coalesce": Signature("coalesce", "any", 1, variadic=True),
    # Not "if": Python reserves the keyword, so `ast.parse("if(a, b, c)")` raises
    # SyntaxError. The name says the three-argument shape out loud.
    # date_forward=(1, 2): if_else forwards its `then`/`else` branches, never its
    # boolean condition at position 0.
    "if_else": Signature("if_else", "any", 3, date_forward=(1, 2)),
    "exists": Signature("exists", "boolean", 1),
    "is_null": Signature("is_null", "boolean", 1),
    "is_empty": Signature("is_empty", "boolean", 1),
    "eq": Signature("eq", "boolean", 2),
    "lt": Signature("lt", "boolean", 2),
    "gt": Signature("gt", "boolean", 2),
    "contains": Signature("contains", "boolean", 2),
    "add_days": Signature("add_days", "date", 2, date_arguments=(0,)),
    "days_between": Signature("days_between", "number", 2, date_arguments=(0, 1)),
    "min": Signature("min", "any", 1, variadic=True),
    "max": Signature("max", "any", 1, variadic=True),
    "first": Signature("first", "any", 1),
    "join": Signature("join", "string", 2),
    # Variadic over SCALARS, unlike `join`, which takes a separator and a list.
    # Building a payload means putting several values and their separators in one
    # string, and a list literal is not part of this language -- `parse_rule`
    # refuses one.
    "concat": Signature("concat", "string", 1, variadic=True),
    # Two arguments, and the second is a NAMED pattern rather than a strftime
    # format. See `DATE_PATTERNS`.
    "format_date": Signature("format_date", "string", 2, date_arguments=(0,)),
}

#: The patterns `format_date` accepts, and the whole set of them.
#:
#: An allowlist rather than free strftime, for two reasons. A free pattern in a
#: configuration file is a typo that nothing catches until a pass carries it --
#: and this language exists precisely so that a configuration cannot express a
#: wrong pass. And `%` sequences travel badly: the same value may pass through a
#: ConfigParser or a shell somewhere downstream, which is a class of surprise
#: this project has already paid for.
#:
#: A name that is not here fails when the rule is PARSED, so at startup, not on
#: the first request.
DATE_PATTERNS: dict[str, str] = {
    "YYYYMMDD": "%Y%m%d",
    "YYYY-MM-DD": "%Y-%m-%d",
}


def _check_date_pattern(node: ast.Call, source: str) -> None:
    """Refuse a `format_date` pattern that is not in the allowlist.

    The pattern has to be a literal: a pattern computed from a field could not
    be checked here, and "checked at startup" is the whole promise of this
    module.
    """
    pattern = node.args[1]
    if not isinstance(pattern, ast.Constant) or not isinstance(pattern.value, str):
        raise RuleError(
            f"format_date() needs a literal pattern in rule {source!r}; "
            f"one of: {', '.join(sorted(DATE_PATTERNS))}."
        )
    if pattern.value not in DATE_PATTERNS:
        raise RuleError(
            f"format_date() does not know the pattern {pattern.value!r} in rule {source!r}. "
            f"Known patterns: {', '.join(sorted(DATE_PATTERNS))}."
        )


def parse_rule(source: str) -> ast.Expression:
    """Parse a rule and reject everything outside the closed language."""
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as error:
        raise RuleError(f"Cannot parse rule {source!r}: {error}") from error

    for node in ast.walk(tree):
        if isinstance(node, ast.Expression | ast.Name | ast.Load | ast.Constant):
            continue
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise RuleError(f"Only named function calls are allowed in {source!r}.")
            if node.func.id not in FUNCTIONS:
                raise RuleError(
                    f"Rule {source!r} calls {node.func.id!r}, which is not one of: "
                    f"{', '.join(sorted(FUNCTIONS))}."
                )
            if node.keywords:
                raise RuleError(f"Keyword arguments are not allowed in {source!r}.")
            signature = FUNCTIONS[node.func.id]
            argument_count = len(node.args)
            if signature.variadic:
                if argument_count < signature.arity:
                    raise RuleError(
                        f"{node.func.id!r} expects at least {signature.arity} argument(s), "
                        f"got {argument_count}, in rule {source!r}."
                    )
            elif argument_count != signature.arity:
                raise RuleError(
                    f"{node.func.id!r} expects {signature.arity} argument(s), "
                    f"got {argument_count}, in rule {source!r}."
                )
            if node.func.id == "format_date":
                _check_date_pattern(node, source)
            continue
        raise RuleError(
            f"{type(node).__name__} is not allowed in a rule. Rule {source!r} may only use "
            "function calls, field references, constants and literals."
        )
    return tree


def _as_date(value: Any) -> datetime.date | None:
    """Turn an ISO string, date or datetime into a real date; None stays None.

    `datetime.datetime` is checked before `datetime.date` because `datetime`
    is a subclass of `date`: an `isinstance(value, datetime.date)` check alone
    is also true for a `datetime` and would return it unreduced, breaking
    arithmetic against a plain `date` later.
    """
    if value is None:
        return value
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str):
        try:
            return datetime.date.fromisoformat(value[:10])
        except ValueError as error:
            raise RuleError(f"{value!r} is not an ISO date.") from error
    raise RuleError(f"{value!r} cannot be read as a date.")


def _present(values: Sequence[Any]) -> list[Any]:
    return [value for value in values if value is not None]


def evaluate(
    expression: ast.Expression,
    payload: dict[str, Any],
    constants: dict[str, Any],
    datetime_fields: set[str],
    today: datetime.date | None = None,
    computed: Mapping[str, Any] | None = None,
) -> Any:
    """Evaluate a parsed rule against one payload.

    `computed` carries the values of an earlier round -- the derived fields,
    when a payload rule is being evaluated. It is empty for a derived rule,
    which is what keeps the rounds apart: round one cannot see round two, and
    neither round can see itself.

    A name resolves as constant, then computed value, then payload key. A
    computed value therefore SHADOWS a stored key of the same name. That is
    deliberate: the view declares the computed field, the payload merely
    happens to carry the key, and a reader looks at the view first.
    `validate_config` refuses the collision anyway, so this only decides what
    happens to a payload key the view never declared.
    """
    reference_day = today or datetime.date.today()
    resolved = computed or {}

    def resolve(node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return resolve(node.body)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in constants:
                return constants[node.id]
            if node.id in resolved:
                value = resolved[node.id]
                # An earlier round may already have produced a real date; the
                # coercion is idempotent and keeps a round-one string honest.
                return _as_date(value) if node.id in datetime_fields else value
            value = payload.get(node.id)
            return _as_date(value) if node.id in datetime_fields else value
        if isinstance(node, ast.Call):
            return call(node)
        raise RuleError(f"{type(node).__name__} cannot be evaluated.")

    def call(node: ast.Call) -> Any:
        if not isinstance(node.func, ast.Name):  # pragma: no cover - parse_rule rejects this
            raise RuleError("Only named function calls are allowed.")
        name = node.func.id
        if name == "if_else":
            condition, then, otherwise = node.args
            return resolve(then) if resolve(condition) else resolve(otherwise)
        if name == "exists":
            target = node.args[0]
            if not isinstance(target, ast.Name):
                return False
            return target.id in payload or target.id in resolved
        arguments = [resolve(argument) for argument in node.args]
        return apply(name, arguments)

    def apply(name: str, arguments: list[Any]) -> Any:  # noqa: PLR0911
        match name:
            case "today" | "now":
                return reference_day
            case "coalesce":
                present = _present(arguments)
                return present[0] if present else None
            case "is_null":
                return arguments[0] is None
            case "is_empty":
                return arguments[0] in (None, "", [], {})
            case "eq":
                return arguments[0] == arguments[1]
            case "lt":
                return arguments[0] < arguments[1]
            case "gt":
                return arguments[0] > arguments[1]
            case "contains":
                container = arguments[0] or []
                return arguments[1] in container
            case "add_days":
                base = _as_date(arguments[0])
                return None if base is None else base + datetime.timedelta(days=arguments[1])
            case "days_between":
                left, right = _as_date(arguments[0]), _as_date(arguments[1])
                return None if left is None or right is None else (left - right).days
            case "min":
                present = _present(arguments)
                return min(present) if present else None
            case "max":
                present = _present(arguments)
                return max(present) if present else None
            case "first":
                value = arguments[0]
                return value[0] if value else None
            case "join":
                separator, values = arguments[0], arguments[1] or []
                return separator.join(str(value) for value in values)
            case "concat":
                # A missing value becomes the empty string, never the text
                # "None". `str(None)` on a pass is the kind of defect that
                # reads as a real value to everyone except the reader that
                # rejects it.
                return "".join("" if value is None else str(value) for value in arguments)
            case "format_date":
                value, pattern = _as_date(arguments[0]), arguments[1]
                # A missing date stays missing rather than becoming "". The
                # caller decides what an absent value means; `coalesce` is
                # right there for a default.
                return None if value is None else value.strftime(DATE_PATTERNS[pattern])
        raise RuleError(f"{name!r} has no implementation.")  # pragma: no cover

    return resolve(expression)
