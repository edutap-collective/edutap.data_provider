"""Application factory."""

from fastapi import APIRouter, FastAPI

from .errors import install_error_handlers
from .routers import router

health_router = APIRouter()


@health_router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Report that the process is up."""
    return {"status": "ok"}


def create_app() -> FastAPI:
    """Build the FastAPI application."""
    app = FastAPI(title="eduTAP data provider", version="0.1.0")
    install_error_handlers(app)
    app.include_router(health_router)
    app.include_router(router)
    return app
