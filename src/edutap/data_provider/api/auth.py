"""Bearer authentication."""

import secrets
from typing import Annotated

from fastapi import Depends, Header

from ..settings import Settings, get_settings
from .errors import ProblemError


def _presented_token(authorization: str) -> str:
    """Return the credential of an `Authorization: Bearer …` header, empty if absent.

    The scheme is public framing, not a secret, and RFC 7235 makes it
    case-insensitive — so it is matched here, in plain non-constant time, and only
    the credential itself goes into the constant-time comparison.
    """
    scheme, _, token = authorization.partition(" ")
    return token if scheme.lower() == "bearer" else ""


async def require_token(
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str, Header()] = "",
) -> None:
    """Reject anything but the configured bearer token."""
    presented = _presented_token(authorization)
    expected = settings.api_token.get_secret_value()
    # Compared as UTF-8 bytes, not as `str`: `compare_digest` raises TypeError on a
    # `str` holding non-ASCII characters, and the header is attacker-controlled, so
    # comparing strings would turn a hostile header into a 500. An empty credential
    # is rejected outright, so that an empty configured token cannot degrade into
    # "no credential needed".
    accepted = bool(presented) and secrets.compare_digest(
        presented.encode("utf-8"), expected.encode("utf-8")
    )
    if not accepted:
        # One message for every failure: no header, wrong scheme and wrong token stay
        # indistinguishable to the caller.
        raise ProblemError(401, "Unauthorized", "A valid bearer token is required.")
