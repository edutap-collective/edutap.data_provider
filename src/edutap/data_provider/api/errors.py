"""Errors as application/problem+json."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class ProblemError(Exception):
    """An error that becomes a problem document."""

    def __init__(self, status_code: int, title: str, detail: str) -> None:
        """Record the three parts of the document."""
        super().__init__(detail)
        self.status_code = status_code
        self.title = title
        self.detail = detail


def install_error_handlers(app: FastAPI) -> None:
    """Render ProblemError as application/problem+json."""

    @app.exception_handler(ProblemError)
    async def _handle(_: Request, error: ProblemError) -> JSONResponse:
        """Turn one ProblemError into its problem document."""
        return JSONResponse(
            status_code=error.status_code,
            media_type="application/problem+json",
            content={
                "title": error.title,
                "status": error.status_code,
                "detail": error.detail,
            },
        )
