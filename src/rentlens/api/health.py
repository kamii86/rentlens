from time import perf_counter

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from rentlens.database import engine
from rentlens.version import __version__

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/v1/version")
async def version() -> dict[str, str]:
    return {"version": __version__}


@router.get("/api/v1/health")
async def health(response: Response) -> dict:
    start = perf_counter()

    try:
        async with engine.connect() as connection:
            result = await connection.execute(text("SELECT version()"))
            database_version = result.scalar_one()

        response_time_ms = round((perf_counter() - start) * 1000, 2)

        return {
            "status": "ok",
            "components": {
                "postgresql": {
                    "status": "ok",
                    "version": database_version,
                    "response_time_ms": response_time_ms,
                }
            },
        }
    except Exception:
        response_time_ms = round((perf_counter() - start) * 1000, 2)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        
        return {
            "status": "error",
            "components": {
                "postgresql": {
                    "status": "error",
                    "version": None,
                    "response_time_ms": response_time_ms,
                }
            },
        }