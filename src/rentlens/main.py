from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from rentlens.api.health import router as health_router
from rentlens.api.process import load_price_model
from rentlens.api.process import router as process_router
from rentlens.logging_config import configure_logging
from rentlens.version import __version__

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Загружаем модель один раз при запуске приложения.
    app.state.price_model = await run_in_threadpool(load_price_model)

    try:
        yield
    finally:
        app.state.price_model = None


app = FastAPI(
    title="RentLens",
    version=__version__,
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(process_router)
