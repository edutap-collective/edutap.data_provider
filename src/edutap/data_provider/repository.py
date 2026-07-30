"""Reading the two tables. The only module that talks to a database.

The service is read-only: this module issues SELECT statements and nothing else.
`tests/test_repository.py` asserts that by reading this file's source.

There is deliberately no method reading `pass_state`: the API exposes `/catalogue`
and `/lookup` and nothing else. `pass_state` is read through the SQL profile by
`lmu_edutap_backend`, `lmu_edutap_admin_backend`, the callback handlers and the
scheduled tasks. A reader method with no caller here would be dead code inviting
an endpoint the contract does not have.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from .models.db import PersonView


class Repository:
    """Reads person views."""

    def __init__(self, session_factory: async_sessionmaker) -> None:
        """Store the session factory; one session is opened per call."""
        self._session_factory = session_factory

    async def person_view(self, person_uid: str, view_type: str) -> dict[str, Any] | None:
        """Return the payload of one view, or None when the row does not exist."""
        # ty (still pre-release, see models/dbdef.py for the same pattern) does not
        # resolve a SQLModel field to a typed SQLAlchemy column here and picks the
        # single-argument select() overload instead of the catch-all one that matches.
        statement = select(PersonView.data).where(  # ty: ignore[no-matching-overload]
            PersonView.person_uid == person_uid,
            PersonView.view_type == view_type,
        )
        async with self._session_factory() as session:
            result = await session.execute(statement)
            return result.scalar_one_or_none()
