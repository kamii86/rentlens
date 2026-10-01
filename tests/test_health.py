import pytest
from httpx import ASGITransport, AsyncClient

import rentlens.api.health as health_module
from rentlens.main import app
from rentlens.version import __version__


@pytest.mark.asyncio
async def test_healthz() -> None:
    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_version() -> None:
    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/version")

    assert response.status_code == 200
    assert response.json() == {"version": __version__}


@pytest.mark.asyncio
async def test_health_database_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenConnection:
        async def __aenter__(self):
            raise ConnectionError("Database is unavailable")

        async def __aexit__(self, exc_type, exc_value, traceback):
            return None

    class BrokenEngine:
        def connect(self):
            return BrokenConnection()

    monkeypatch.setattr(health_module, "engine", BrokenEngine())

    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/health")

    assert response.status_code == 503
    assert response.json()["status"] == "error"
    assert response.json()["components"]["postgresql"]["status"] == "error"
    assert response.json()["components"]["postgresql"]["version"] is None


@pytest.mark.asyncio
async def test_health_database_available(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResult:
        def scalar_one(self):
            return "PostgreSQL test version"

    class FakeConnection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            return None

        async def execute(self, query):
            return FakeResult()

    class FakeEngine:
        def connect(self):
            return FakeConnection()

    monkeypatch.setattr(health_module, "engine", FakeEngine())

    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/health")

    data = response.json()

    assert response.status_code == 200
    assert data["status"] == "ok"
    assert data["components"]["postgresql"]["status"] == "ok"
    assert data["components"]["postgresql"]["version"] == "PostgreSQL test version"
    assert data["components"]["postgresql"]["response_time_ms"] >= 0
