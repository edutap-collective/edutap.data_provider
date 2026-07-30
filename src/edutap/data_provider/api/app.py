"""Application factory."""

from fastapi import APIRouter, FastAPI

health_router = APIRouter()


@health_router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Report that the process is up."""
    return {"status": "ok"}


def create_app() -> FastAPI:
    """Build the FastAPI application."""
    app = FastAPI(title="eduTAP data provider", version="0.1.0")
    app.include_router(health_router)
    return app
