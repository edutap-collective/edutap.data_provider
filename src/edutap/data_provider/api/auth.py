"""Bearer authentication."""

from typing import Annotated

from fastapi import Depends, Header

from ..settings import Settings, get_settings
from .errors import ProblemError


async def require_token(
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str, Header()] = "",
) -> None:
    """Reject anything but the configured bearer token."""
    expected = f"Bearer {settings.api_token.get_secret_value()}"
    if authorization != expected:
        raise ProblemError(401, "Unauthorized", "A valid bearer token is required.")
