"""The two endpoints of the contract."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..catalogue import CatalogueEntry, UnknownViewType, catalogue_for
from ..config import ProviderConfig
from ..repository import Repository
from ..rules import evaluate, parse_rule
from ..validation import datetime_fields
from .auth import require_token
from .dependencies import get_provider_config, get_repository
from .errors import ProblemError

router = APIRouter(dependencies=[Depends(require_token)])

# Annotated rather than `config: ProviderConfig = Depends(...)`: a call in an
# argument default is B008, and this project's ruff configuration does not carry a
# fastapi exemption list for it. Annotated is also the shape FastAPI itself now
# documents, and it keeps the parameter's real default (there is none) visible.
ConfigDependency = Annotated[ProviderConfig, Depends(get_provider_config)]
RepositoryDependency = Annotated[Repository, Depends(get_repository)]


class LookupRequest(BaseModel):
    """What a consumer asks for."""

    person_uid: str
    view_type: str
    fields: list[str]


@router.get("/catalogue", response_model=list[CatalogueEntry])
async def catalogue(view_type: str, config: ConfigDependency) -> list[CatalogueEntry]:
    """Return the field list of one view."""
    try:
        return catalogue_for(config, view_type)
    except UnknownViewType as error:
        raise ProblemError(404, "Unknown view type", str(error)) from error


@router.post("/lookup")
async def lookup(
    request: LookupRequest,
    config: ConfigDependency,
    repository: RepositoryDependency,
) -> dict[str, Any]:
    """Return exactly the requested fields for one person."""
    try:
        entries = {entry.key: entry for entry in catalogue_for(config, request.view_type)}
    except UnknownViewType as error:
        raise ProblemError(404, "Unknown view type", str(error)) from error

    unknown = sorted(set(request.fields) - set(entries))
    if unknown:
        raise ProblemError(
            400,
            "Unknown field",
            f"View {request.view_type!r} does not offer: {', '.join(unknown)}.",
        )

    payload = await repository.person_view(request.person_uid, request.view_type)
    if payload is None:
        raise ProblemError(404, "Unknown person", f"No {request.view_type!r} view for this person.")

    view = config.views[request.view_type]
    dates = datetime_fields(config, request.view_type)
    answer: dict[str, Any] = {}
    for key in request.fields:
        if entries[key].derived:
            value = evaluate(parse_rule(view.derived[key].rule), payload, config.constants, dates)
        else:
            value = payload.get(key)
        if value is not None:
            answer[key] = value.isoformat() if hasattr(value, "isoformat") else value
    return answer
