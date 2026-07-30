"""Cross-validation of rules against the fields and kinds they use.

Everything here is fatal at startup. A rule that reads a field which no producer
writes, or does date arithmetic on a field that is not a date, is a defect that must
surface before the service accepts a request — not as a silent wrong validity on an
issued pass.
"""

import ast

from .config import ConfigError, ProviderConfig
from .rules import FUNCTIONS, RuleError, parse_rule
from .vocabulary import FieldKind


def _rule_names(tree: ast.Expression) -> set[str]:
    """Return the field or constant names a rule reads."""
    return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} - set(FUNCTIONS)


def referenced_fields(config: ProviderConfig, view_type: str) -> set[str]:
    """Return every field a producer must write for this view.

    Declared fields plus the inputs of every rule, minus named constants and the
    derived names the rules themselves produce.
    """
    view = config.views[view_type]
    names = set(view.fields)
    for derived in view.derived.values():
        names |= _rule_names(parse_rule(derived.rule))
    return names - set(config.constants) - set(view.derived)


def datetime_fields(config: ProviderConfig, view_type: str) -> set[str]:
    """Return the fields of this view that declare DATETIME."""
    view = config.views[view_type]
    stored = {name for name, spec in view.fields.items() if FieldKind.DATETIME in spec.kinds}
    computed = {name for name, spec in view.derived.items() if FieldKind.DATETIME in spec.kinds}
    return stored | computed


def _check_view(config: ProviderConfig, view_type: str) -> list[str]:
    view = config.views[view_type]
    known = set(view.fields) | set(view.derived) | set(config.constants)
    date_like = datetime_fields(config, view_type) | set(config.constants)
    problems: list[str] = []

    for name, derived in view.derived.items():
        try:
            tree = parse_rule(derived.rule)
        except RuleError as error:
            problems.append(f"{view_type}.{name}: {error}")
            continue

        for referenced in sorted(_rule_names(tree) - known):
            problems.append(
                f"{view_type}.{name}: rule reads {referenced!r}, which is neither a declared "
                "field nor a constant — no producer would know to write it."
            )

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            signature = FUNCTIONS[node.func.id]
            for position in signature.date_arguments:
                if position >= len(node.args):
                    continue
                argument = node.args[position]
                if isinstance(argument, ast.Name) and argument.id not in date_like:
                    problems.append(
                        f"{view_type}.{name}: {node.func.id}() needs a date, but "
                        f"{argument.id!r} does not declare DATETIME."
                    )
    return problems


def validate_config(config: ProviderConfig) -> None:
    """Raise :class:`ConfigError` listing every problem across all views."""
    problems: list[str] = []
    for view_type in config.views:
        problems.extend(_check_view(config, view_type))
    if problems:
        raise ConfigError("Invalid view configuration:\n  " + "\n  ".join(problems))
