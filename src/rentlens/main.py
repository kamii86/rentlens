from fastapi import FastAPI

from rentlens.api.health import router as health_router
from rentlens.logging_config import configure_logging
from rentlens.version import __version__

configure_logging()

app = FastAPI(
    title="RentLens",
    version=__version__,
)

app.include_router(health_router)
