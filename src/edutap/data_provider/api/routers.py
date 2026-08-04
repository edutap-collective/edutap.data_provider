"""The two endpoints of the contract."""

import logging
from typing import Annotated, Any

import sentry_sdk
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..catalogue import CatalogueEntry, UnknownViewType, catalogue_for
from ..config import ProviderConfig
from ..observability import get_observability_settings, pseudonym
from ..repository import Repository
from ..rules import RuleError, evaluate, parse_rule
from ..validation import datetime_fields
from .auth import require_token
from .dependencies import get_provider_config, get_repository
from .errors import ProblemError

router = APIRouter(dependencies=[Depends(require_token)])

_LOGGER = logging.getLogger(__name__)

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
    # The only place in the process that holds a person_uid. Sentry is configured
    # with max_request_body_size="never", so nothing downstream can recover it -- and
    # nothing downstream should. What survives is a keyed pseudonym: enough to see
    # that one person failed repeatedly, not enough to learn who.
    tag = pseudonym(request.person_uid, get_observability_settings().pseudonym_salt)
    # The client check is not a micro-optimisation. `set_tag` writes to the
    # isolation scope, and it is Sentry's Starlette integration that forks a fresh
    # one per request -- but that integration is only installed by `sentry_sdk.init`.
    # In a deployment with a salt and no DSN, which is perfectly ordinary, every
    # request would otherwise write into one ambient, never-reset, process-global
    # scope that nothing ever reads or clears.
    if tag is not None and sentry_sdk.get_client().is_active():
        sentry_sdk.set_tag("person", tag)

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
    # Set only on a RuleError, and read after the loop: see the comment on the
    # `except` clause below for why the raise itself has to live out here.
    derivation_failure: str | None = None
    for key in request.fields:
        if entries[key].derived:
            # Not dead code, and not something startup validation makes redundant:
            # `validate_config` type-checks the rule's static AST, while this failure
            # mode lives in the row. A field declared DATETIME whose stored value is
            # not an ISO date (say a German "02.08.2026") makes `rules._as_date` raise
            # at read time. Without this catch the RuleError leaves the route unhandled
            # and Starlette answers text/plain, breaking the one uniform
            # application/problem+json contract this API promises.
            try:
                value = evaluate(
                    parse_rule(view.derived[key].rule), payload, config.constants, dates
                )
            except RuleError:
                # `rules._as_date` puts the offending stored value verbatim in a
                # RuleError's own message, and this package's ProblemError message
                # never repeats it -- but that is not the whole picture. Measured:
                # sentry-sdk's Starlette integration captures an exception once it
                # reaches a *registered* handler and its response carries a 5xx
                # status, which ProblemError's does, and it sends the full
                # `__cause__` chain, not only the exception it captures directly.
                # `raise ProblemError(...) from error` therefore still put the
                # stored value on the wire. `from None` would not have fixed it
                # either: it only sets `__suppress_context__`, leaving `__context__`
                # pointing at the RuleError, invisible in a printed traceback but
                # still there for anything that walks the chain itself -- the same
                # property `api/app.py`'s `_load_configuration` documents for a
                # `ValidationError` carrying the API token and the database
                # password. The fix is the same one used there: record what an
                # operator needs and raise after this block, with no exception
                # being handled at that point, so the RuleError is genuinely
                # absent from the new exception's object graph rather than merely
                # hidden from it. The cost is real -- the traceback no longer shows
                # which rule function failed -- and is accepted for the same
                # reason it was accepted there: the field name and view type below
                # are what an operator gets instead, and the stored row itself is
                # still one query away in the database.
                derivation_failure = (
                    f"Rule for field {key!r} of view {request.view_type!r} failed on the "
                    "stored data for this person."
                )
                break
        else:
            value = payload.get(key)
        if value is not None:
            answer[key] = value.isoformat() if hasattr(value, "isoformat") else value

    if derivation_failure is not None:
        # The only server-side record that this happened. A ProblemError is answered
        # by Starlette's ExceptionMiddleware, several layers inside
        # ServerErrorMiddleware, so -- unlike an exception nobody handled -- it is
        # never re-raised and uvicorn logs nothing but the access line. Without this
        # call, an operator running without a DSN would have no way to learn that a
        # row is broken, let alone which field of which view: the comment above says
        # the stored row is one query away in the database, and that presumes you
        # know which row to go and look at.
        #
        # Safe to log, on the same terms as everything else in this module: the
        # message names the field and the view and never a value, the person appears
        # only as the keyed pseudonym computed above, and `max_breadcrumbs=0` (see
        # `observability.sentry_options`) means a log record cannot become a Sentry
        # breadcrumb in the first place.
        #
        # Measured, so that it is not a surprise later: where a DSN *is* configured,
        # sentry-sdk's LoggingIntegration also turns this record into an event of
        # its own (its default `event_level` is ERROR), so Bugsink sees two entries
        # for one failure -- this message, and the ProblemError the request raises
        # below. The duplicate is accepted rather than suppressed with a third
        # mechanism: its content is exactly the two safe identifiers above, and the
        # deployment this line exists for is the one with no DSN at all.
        _LOGGER.error(
            "%s Person: %s.", derivation_failure, tag if tag is not None else "no salt configured"
        )
        # 500, not 4xx: the request was well-formed and no different request would
        # succeed. The defect is in data this service owns, so the blame belongs on
        # the server side. Raised here, after the loop and its try/except have both
        # already run to completion, so nothing is being handled at this point.
        raise ProblemError(500, "Derived field cannot be computed", derivation_failure)

    return answer
