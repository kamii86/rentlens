from fastapi import FastAPI

from rentlens.api.health import router as health_router

app = FastAPI(
    title="RentLens",
    version="0.1.0",
)

app.include_router(health_router)
