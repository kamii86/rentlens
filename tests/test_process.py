from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

import rentlens.api.tasks as tasks_api
from rentlens.main import app
from rentlens.task_broker import QueueFull


@pytest.fixture
def api_mocks(monkeypatch):
    publish = AsyncMock()
    save = AsyncMock()

    monkeypatch.setattr(
        app.state,
        "publisher",
        SimpleNamespace(publish=publish),
        raising=False,
    )
    monkeypatch.setattr(tasks_api, "record_accepted", save)

    return publish, save


async def post_task(payload):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        return await client.post(
            "/api/v1/tasks",
            json=payload,
        )


@pytest.mark.asyncio
async def test_task_accepted(api_mocks):
    publish, save = api_mocks

    payload = {
        "square_feet": 900,
        "bedrooms": 2,
        "bathrooms": 1,
        "latitude": 40.7128,
        "longitude": -74.006,
        "cityname": "New York",
        "state": "NY",
        "pets_allowed": "Cats,Dogs",
    }

    response = await post_task(payload)

    assert response.status_code == 202

    data = response.json()

    assert data["status"] == "ACCEPTED"
    assert data["status_url"] == (f"/api/v1/tasks/{data['task_id']}")

    UUID(data["task_id"])

    publish.assert_awaited_once()
    save.assert_awaited_once()

    assert publish.await_args.args[0] == data["task_id"]
    assert save.await_args.args[0] == data["task_id"]


@pytest.mark.asyncio
async def test_missing_optional_features(api_mocks):
    publish, save = api_mocks

    response = await post_task({"square_feet": 900})

    assert response.status_code == 202

    publish.assert_awaited_once()
    save.assert_awaited_once()

    payload = publish.await_args.args[1]

    assert payload["square_feet"] == 900
    assert payload["bedrooms"] is None
    assert payload["bathrooms"] is None
    assert payload["cityname"] is None
    assert payload["state"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"square_feet": -100},
        {"square_feet": 900, "bedrooms": -1},
        {"square_feet": 900, "latitude": 100},
        {"square_feet": 900, "unexpected_field": "value"},
        {},
    ],
)
async def test_invalid_input(api_mocks, payload):
    publish, save = api_mocks

    response = await post_task(payload)

    assert response.status_code == 422

    publish.assert_not_awaited()
    save.assert_not_awaited()


@pytest.mark.asyncio
async def test_queue_full(api_mocks):
    publish, save = api_mocks

    publish.side_effect = QueueFull("Queue is full")

    response = await post_task({"square_feet": 900})

    assert response.status_code == 503
    assert response.headers["retry-after"] == str(tasks_api.settings.retry_after)

    save.assert_not_awaited()


@pytest.mark.asyncio
async def test_broker_unavailable(api_mocks):
    publish, save = api_mocks

    publish.side_effect = ConnectionError("RabbitMQ unavailable")

    response = await post_task({"square_feet": 900})

    assert response.status_code == 503
    assert "retry-after" in response.headers

    save.assert_not_awaited()


@pytest.mark.asyncio
async def test_task_status(monkeypatch):
    task_id = str(uuid4())
    now = datetime.now(UTC)

    get_task = AsyncMock(
        return_value={
            "id": task_id,
            "status": "COMPLETED",
            "attempts": 1,
            "predicted_price": 4331.42,
            "error": None,
            "created_at": now,
            "finished_at": now,
        }
    )

    monkeypatch.setattr(tasks_api, "get_task", get_task)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(f"/api/v1/tasks/{task_id}")

    assert response.status_code == 200

    data = response.json()

    assert data["task_id"] == task_id
    assert data["status"] == "COMPLETED"
    assert data["attempts"] == 1
    assert data["predicted_price"] == 4331.42

    get_task.assert_awaited_once_with(task_id)


@pytest.mark.asyncio
async def test_task_not_found(monkeypatch):
    get_task = AsyncMock(return_value=None)

    monkeypatch.setattr(tasks_api, "get_task", get_task)

    task_id = str(uuid4())

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(f"/api/v1/tasks/{task_id}")

    assert response.status_code == 404

    get_task.assert_awaited_once_with(task_id)
