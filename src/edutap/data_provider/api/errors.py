"""Errors as application/problem+json."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# The only thing a consumer learns about an unexpected failure. Deliberately says
# nothing beyond "it was us, and it was not your request": an arbitrary exception's
# message can quote stored personal data — `RuleError` prints the offending value —
# and its type name can be just as telling. The traceback belongs in the server log,
# which is where it still goes; see `_handle_unexpected`.
UNEXPECTED_DETAIL = "The request could not be completed because of an internal error."


class ProblemError(Exception):
    """An error that becomes a problem document."""

    def __init__(self, status_code: int, title: str, detail: str) -> None:
        """Record the three parts of the document."""
        super().__init__(detail)
        self.status_code = status_code
        self.title = title
        self.detail = detail


def _problem(status_code: int, title: str, detail: str) -> JSONResponse:
    """Render the three parts of a problem document as one response."""
    return JSONResponse(
        status_code=status_code,
        media_type="application/problem+json",
        content={"title": title, "status": status_code, "detail": detail},
    )


def install_error_handlers(app: FastAPI) -> None:
    """Render every error this API answers with as application/problem+json."""

    @app.exception_handler(ProblemError)
    async def _handle(_: Request, error: ProblemError) -> JSONResponse:
        """Turn one ProblemError into its problem document."""
        return _problem(error.status_code, error.title, error.detail)

    @app.exception_handler(Exception)
    async def _handle_unexpected(_: Request, __: Exception) -> JSONResponse:
        """Keep an exception nobody anticipated inside the problem+json contract.

        The two handlers do not compete. Starlette's `build_middleware_stack` routes
        a handler registered for `Exception` (or 500) into `ServerErrorMiddleware`,
        the outermost layer, and every other handler into `ExceptionMiddleware`,
        which sits further in. A `ProblemError` is therefore answered by `_handle`
        before it can ever reach this one, and keeps its own status, title and detail.

        The exception is not swallowed. `ServerErrorMiddleware` sends whatever this
        handler returns and then re-raises ("We always continue to raise the
        exception. This allows servers to log the error"), so uvicorn still logs the
        full traceback. That is also why a `TestClient` built with the default
        `raise_server_exceptions=True` sees the exception rather than this document.

        Nothing about the exception goes into the response: see `UNEXPECTED_DETAIL`.
        """
        return _problem(500, "Internal server error", UNEXPECTED_DETAIL)
