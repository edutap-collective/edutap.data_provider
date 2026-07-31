"""The exposed field list of a view.

Derived fields stand here as equals: a consumer sees them without needing to know
they come into being at read time. Fields a row carries but the configuration never
mentions are absent — they are raw material for rules, not output.
"""

from pydantic import BaseModel

from .config import ProviderConfig
from .vocabulary import FieldKind


class UnknownViewType(Exception):
    """The requested view type is not configured."""


class CatalogueEntry(BaseModel):
    """One field a consumer of this view may ask for."""

    key: str
    kinds: list[FieldKind]
    derived: bool
    description: str | None = None


def catalogue_for(config: ProviderConfig, view_type: str) -> list[CatalogueEntry]:
    """Return the catalogue of one view, sorted by key."""
    if view_type not in config.views:
        raise UnknownViewType(
            f"View type {view_type!r} is not configured. Known: "
            f"{', '.join(sorted(config.views)) or '(none)'}."
        )
    view = config.views[view_type]
    entries = [
        CatalogueEntry(key=key, kinds=spec.kinds, derived=False, description=spec.description)
        for key, spec in view.fields.items()
    ]
    entries += [
        CatalogueEntry(key=key, kinds=spec.kinds, derived=True, description=spec.description)
        for key, spec in view.derived.items()
    ]
    return sorted(entries, key=lambda entry: entry.key)
