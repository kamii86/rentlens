from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from faststream.rabbit import TestRabbitBroker

from rentlens import worker


@pytest.fixture
def mocked_worker(monkeypatch):
    started = AsyncMock(return_value=1)
    completed = AsyncMock()
    failed = AsyncMock()
    prediction = Mock(return_value=4331.42)

    monkeypatch.setattr(worker, "start_attempt", started)
    monkeypatch.setattr(worker, "complete", completed)
    monkeypatch.setattr(worker, "fail", failed)
    monkeypatch.setattr(
        worker,
        "model",
        SimpleNamespace(predict=prediction),
    )
    monkeypatch.setattr(
        worker,
        "settings",
        replace(worker.settings, inference_seconds=0),
    )

    return started, completed, failed, prediction


@pytest.mark.asyncio
async def test_successful_processing(mocked_worker):
    started, completed, failed, prediction = mocked_worker
    task_id = str(uuid4())

    payload = {
        "task_id": task_id,
        "features": {"square_feet": 900},
    }

    async with TestRabbitBroker(worker.broker) as broker:
        await broker.publish(
            payload,
            queue=worker.settings.queue_name,
        )

    started.assert_awaited_once_with(task_id, payload)
    completed.assert_awaited_once_with(task_id, 4331.42)
    failed.assert_not_awaited()
    prediction.assert_called_once()


@pytest.mark.asyncio
async def test_idempotent_processing(mocked_worker):
    started, completed, failed, prediction = mocked_worker
    started.return_value = None

    task_id = str(uuid4())
    payload = {
        "task_id": task_id,
        "features": {"square_feet": 900},
    }

    async with TestRabbitBroker(worker.broker) as broker:
        await broker.publish(
            payload,
            queue=worker.settings.queue_name,
        )

    started.assert_awaited_once()
    completed.assert_not_awaited()
    failed.assert_not_awaited()
    prediction.assert_not_called()


@pytest.mark.asyncio
async def test_failed_task(mocked_worker):
    started, completed, failed, prediction = mocked_worker
    started.return_value = 3

    task_id = str(uuid4())
    payload = {
        "task_id": task_id,
        "features": {},
    }

    async with TestRabbitBroker(worker.broker) as broker:
        await broker.publish(
            payload,
            queue=worker.settings.queue_name,
        )

    started.assert_awaited_once()
    completed.assert_not_awaited()
    failed.assert_awaited_once()
    prediction.assert_not_called()
    assert failed.await_args.args[0] == task_id
