"""View configuration: what a view exposes and how derived fields are computed."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from .vocabulary import FieldKind


class ConfigError(Exception):
    """The view configuration cannot be used. Fatal at startup."""


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
        raw = yaml.safe_load(path.read_text()) or {}
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
