"""Package-local metadata and declarative base.

The naming convention is COPIED from `edutap.db_definitions`, deliberately not
imported: importing would give this deployed service a runtime dependency on a tool
that is never deployed. `edutap-dbdef check` verifies that every package uses the
same convention.

The metadata is package-local because `SQLModel.metadata` is a process-wide
singleton — a generator that cannot tell packages apart cannot order, split or diff
them.
"""

from sqlalchemy import MetaData
from sqlmodel import SQLModel

NAMING_CONVENTION: dict[str, str] = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Base(SQLModel):
    """Declarative base binding this package's tables to its own metadata."""

    metadata = metadata
