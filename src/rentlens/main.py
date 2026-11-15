import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from rentlens.api.health import router as health_router
from rentlens.api.tasks import router as tasks_router
from rentlens.logging_config import configure_logging
from rentlens.metrics import ApiMetricsMiddleware
from rentlens.task_broker import TaskPublisher
from rentlens.task_store import create_tables
from rentlens.telemetry import configure_telemetry, shutdown_telemetry
from rentlens.version import __version__

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_telemetry("rentlens-api")
    publisher = TaskPublisher()

    try:
        await create_tables()
        await publisher.start()

        app.state.publisher = publisher

        logger.info(
            "API started",
            extra={"event": "startup_completed"},
        )

        yield

    finally:
        logger.info(
            "API shutdown started",
            extra={"event": "shutdown_started"},
        )

        try:
            await publisher.close()
        finally:
            logger.info(
                "API resources closed",
                extra={"event": "shutdown_completed"},
            )
            await asyncio.to_thread(shutdown_telemetry)


app = FastAPI(
    title="RentLens",
    version=__version__,
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(tasks_router)
app.add_middleware(ApiMetricsMiddleware)
