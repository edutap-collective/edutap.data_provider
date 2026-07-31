"""View configuration: what a view exposes and how derived fields are computed."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError
from yaml.constructor import ConstructorError
from yaml.error import Mark

from .vocabulary import FieldKind


class ConfigError(Exception):
    """The view configuration cannot be used. Fatal at startup."""


class _DuplicateKeyError(ConstructorError):
    """A mapping in the configuration repeats a key."""

    def __init__(self, key: Any, mark: Mark) -> None:
        super().__init__(None, None, f"duplicate key {key!r}", mark)
        self.key = key
        # PyYAML counts lines from zero; whoever opens the file in an editor does not.
        self.line = mark.line + 1


class _UniqueKeyLoader(yaml.SafeLoader):
    """A `SafeLoader` that refuses to silently drop a repeated mapping key.

    Plain `yaml.safe_load` keeps the last of two identically named keys. A
    copy-pasted view block would therefore start the service without a word and
    serve the second definition — the silent wrong answer this package exists to
    prevent. The check sits at load time, so it covers every mapping in the
    document: view names, field names inside a view, constants.
    """

    def _refuse_duplicates(self, node: yaml.MappingNode, deep: bool) -> None:
        """Raise if this mapping, as written, names the same key twice."""
        # A list, not a set: a key need not be hashable at this point, and an
        # unhashable one must reach PyYAML's own error rather than raise TypeError
        # here. Configuration documents are small, so the linear scan costs nothing.
        seen: list[Any] = []
        for key_node, _ in node.value:
            # `<<` is an instruction, not a key: it carries the merge tag, which has
            # no constructor, so constructing it would raise. Repeating it is legal
            # too — each occurrence merges another anchor — so it is skipped rather
            # than counted. `flatten_mapping` resolves it, and the override below
            # makes sure what it pulls in was checked as well.
            if key_node.tag == "tag:yaml.org,2002:merge":
                continue
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise _DuplicateKeyError(key, key_node.start_mark)
            seen.append(key)

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        """Construct a mapping, refusing a key that was already seen.

        The scan runs on the mapping as it was *written*, before `super()` resolves
        any merge key. That order is the whole point: after the merge, a key that was
        inherited and then deliberately overridden appears twice in the same list, so
        a later scan would report the most ordinary correct use of `<<` as a
        duplicate. Scanning first lets an author inherit a key and override it, while
        two literally repeated keys are still refused.
        """
        self._refuse_duplicates(node, deep)
        return super().construct_mapping(node, deep=deep)

    def flatten_mapping(self, node: yaml.MappingNode) -> None:
        """Resolve merge keys, checking each source mapping on the way in.

        Without this override a duplicate could be smuggled in through an anchor
        written *at* the merge site (`<<: &defaults {…}`), because PyYAML descends
        into a merge source by calling `flatten_mapping` on it, never
        `construct_mapping` — so the scan above would never see that mapping. Its
        repeated key would then be resolved by the plain last-one-wins rule and
        silently change what a view exposes: exactly the failure this loader exists
        to prevent. An anchor that is also bound to an ordinary key is checked twice,
        which costs nothing and yields the same answer.

        Recursion needs no special handling: `super()` calls `self.flatten_mapping`
        for nested merges, which lands here again.
        """
        for key_node, value_node in node.value:
            if key_node.tag != "tag:yaml.org,2002:merge":
                continue
            # `<<: *one` is a mapping; `<<: [*one, *two]` is a sequence of them.
            sources = (
                value_node.value if isinstance(value_node, yaml.SequenceNode) else [value_node]
            )
            for source in sources:
                if isinstance(source, yaml.MappingNode):
                    self._refuse_duplicates(source, deep=False)
        super().flatten_mapping(node)


class FieldSpec(BaseModel):
    """A field the producer writes and the catalogue exposes."""

    kinds: list[FieldKind]
    description: str | None = None


class DerivedSpec(BaseModel):
    """A field computed at read time from other fields of the same row."""

    kinds: list[FieldKind]
    rule: str
    description: str | None = None


class ViewSpec(BaseModel):
    """One view type: what it exposes, stored and derived."""

    description: str | None = None
    fields: dict[str, FieldSpec] = {}
    derived: dict[str, DerivedSpec] = {}


class ProviderConfig(BaseModel):
    """The whole configuration: named constants and the views."""

    constants: dict[str, Any] = {}
    views: dict[str, ViewSpec]


def _normalise_fields(raw: dict[str, Any]) -> dict[str, Any]:
    """Accept the short form `name: [KIND, …]` next to the long mapping form."""
    fields = {}
    for name, value in (raw or {}).items():
        fields[name] = {"kinds": value} if isinstance(value, list) else value
    return fields


def _check_flat_names(view_name: str, names: list[str]) -> None:
    for name in names:
        if "." in name or not name.replace("_", "").isalnum():
            raise ConfigError(
                f"View {view_name!r}: field name {name!r} is not flat. Payloads carry flat "
                "keys — no dots, no nested objects."
            )


def load_config(path: Path) -> ProviderConfig:
    """Load and structurally validate the view configuration."""
    if not path.is_file():
        raise ConfigError(f"View configuration not found: {path}")
    try:
        # S506 matches on the loader's name, not on its base class: `_UniqueKeyLoader`
        # *is* a `yaml.SafeLoader`, so this is `safe_load` plus the duplicate-key
        # check — no arbitrary object can be instantiated here.
        raw = yaml.load(path.read_text(), Loader=_UniqueKeyLoader) or {}  # noqa: S506
    except _DuplicateKeyError as error:
        raise ConfigError(
            f"Duplicate key {error.key!r} in the view configuration: {path}, "
            f"line {error.line}. YAML keeps only the last of two "
            "identical keys, so one of the two definitions would be ignored without "
            "a word. Remove or rename one of them."
        ) from error
    except yaml.YAMLError as error:
        raise ConfigError(f"View configuration is not valid YAML: {path}: {error}") from error
    for view in (raw.get("views") or {}).values():
        if isinstance(view, dict) and "fields" in view:
            view["fields"] = _normalise_fields(view["fields"])
    try:
        config = ProviderConfig.model_validate(raw)
    except ValidationError as error:
        raise ConfigError(f"Invalid view configuration: {error}") from error

    for name, view in config.views.items():
        if not view.fields and not view.derived:
            raise ConfigError(f"View {name!r} is empty: it exposes no fields.")
        _check_flat_names(name, [*view.fields, *view.derived])
        collisions = set(view.fields) & set(view.derived)
        if collisions:
            raise ConfigError(
                f"View {name!r}: {', '.join(sorted(collisions))} is both a stored and a "
                "derived field. A name means one thing."
            )
    return config
