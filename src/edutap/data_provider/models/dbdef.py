"""What this package tells `edutap.db_definitions` about its tables.

`edutap.db_definitions` is a development dependency, never a runtime one — the
service itself never calls it, only the separate CLI tool that renders and applies
DDL. The import is guarded so that a deployment without the tool installed can still
import this module cleanly; `definition` is `None` in that case.
"""

try:
    from edutap.db_definitions import SchemaDefinition
except ModuleNotFoundError:  # pragma: no cover - the service does not need the tool
    SchemaDefinition = None  # ty: ignore[invalid-assignment]

from . import db  # noqa: F401  importing registers the tables on the metadata
from .base import metadata

definition = (
    SchemaDefinition(
        name="edutap.data_provider",
        metadata=metadata,
        version_table="alembic_version_data_provider",
    )
    if SchemaDefinition is not None
    else None
)
