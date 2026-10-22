from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from rentlens.api.health import router as health_router
from rentlens.api.tasks import router as tasks_router
from rentlens.logging_config import configure_logging
from rentlens.task_broker import TaskPublisher
from rentlens.task_store import create_tables
from rentlens.version import __version__

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await create_tables()

    publisher = TaskPublisher()
    await publisher.start()

    app.state.publisher = publisher

    try:
        yield
    finally:
        await publisher.close()


app = FastAPI(
    title="RentLens",
    version=__version__,
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(tasks_router)
