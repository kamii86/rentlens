from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from rentlens import worker


@pytest.fixture
def mocked_worker(monkeypatch):
    start = AsyncMock(return_value=1)
    complete = AsyncMock()
    fail = AsyncMock()
    predict = Mock(return_value=4331.42)

    message = SimpleNamespace(
        ack=AsyncMock(),
        nack=AsyncMock(),
        reject=AsyncMock(),
    )

    monkeypatch.setattr(worker, "start_attempt", start)
    monkeypatch.setattr(worker, "complete", complete)
    monkeypatch.setattr(worker, "fail", fail)
    monkeypatch.setattr(
        worker,
        "model",
        SimpleNamespace(predict=predict),
    )
    monkeypatch.setattr(
        worker,
        "settings",
        replace(
            worker.settings,
            inference_seconds=0,
            max_attempts=3,
        ),
    )

    return SimpleNamespace(
        start=start,
        complete=complete,
        fail=fail,
        predict=predict,
        message=message,
    )


def valid_payload():
    return {
        "task_id": "task-123",
        "features": {"square_feet": 900},
    }


@pytest.mark.asyncio
async def test_missing_task_id(mocked_worker):
    payload = {"features": {"square_feet": 900}}

    await worker.handle_task(payload, mocked_worker.message)

    mocked_worker.message.reject.assert_awaited_once_with(requeue=False)
    mocked_worker.start.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_features_type(mocked_worker):
    payload = {
        "task_id": "task-123",
        "features": "invalid",
    }

    await worker.handle_task(payload, mocked_worker.message)

    mocked_worker.message.reject.assert_awaited_once_with(requeue=False)
    mocked_worker.start.assert_not_awaited()


@pytest.mark.asyncio
async def test_database_start_failure(mocked_worker):
    mocked_worker.start.side_effect = RuntimeError("DB unavailable")

    await worker.handle_task(
        valid_payload(),
        mocked_worker.message,
    )

    mocked_worker.message.nack.assert_awaited_once_with(requeue=True)
    mocked_worker.predict.assert_not_called()


@pytest.mark.asyncio
async def test_completed_task_is_not_reprocessed(mocked_worker):
    mocked_worker.start.return_value = None

    await worker.handle_task(
        valid_payload(),
        mocked_worker.message,
    )

    mocked_worker.message.ack.assert_awaited_once()
    mocked_worker.predict.assert_not_called()
    mocked_worker.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_apartment_goes_to_dlq(mocked_worker):
    mocked_worker.start.return_value = 3

    await worker.handle_task(
        {"task_id": "task-123", "features": {}},
        mocked_worker.message,
    )

    mocked_worker.fail.assert_awaited_once()
    mocked_worker.message.reject.assert_awaited_once_with(requeue=False)
    mocked_worker.predict.assert_not_called()


@pytest.mark.asyncio
async def test_missing_model_goes_to_dlq(
    mocked_worker,
    monkeypatch,
):
    mocked_worker.start.return_value = 3
    monkeypatch.setattr(worker, "model", None)

    await worker.handle_task(
        valid_payload(),
        mocked_worker.message,
    )

    mocked_worker.fail.assert_awaited_once()
    mocked_worker.message.reject.assert_awaited_once_with(requeue=False)


@pytest.mark.asyncio
async def test_prediction_error_goes_to_dlq(mocked_worker):
    mocked_worker.start.return_value = 3
    mocked_worker.predict.side_effect = ValueError("Prediction failed")

    await worker.handle_task(
        valid_payload(),
        mocked_worker.message,
    )

    mocked_worker.fail.assert_awaited_once_with(
        "task-123",
        "Prediction failed",
    )
    mocked_worker.message.reject.assert_awaited_once_with(requeue=False)
    mocked_worker.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_transient_failure_is_requeued(
    mocked_worker,
    monkeypatch,
):
    sleep = AsyncMock()

    monkeypatch.setattr(worker, "model", None)
    monkeypatch.setattr(
        worker,
        "asyncio",
        SimpleNamespace(sleep=sleep),
    )

    await worker.handle_task(
        valid_payload(),
        mocked_worker.message,
    )

    sleep.assert_awaited_once_with(1)
    mocked_worker.message.nack.assert_awaited_once_with(requeue=True)
    mocked_worker.fail.assert_not_awaited()


@pytest.mark.asyncio
async def test_failure_to_save_error_requeues(mocked_worker):
    mocked_worker.start.return_value = 3
    mocked_worker.fail.side_effect = RuntimeError("DB error")
    mocked_worker.predict.side_effect = ValueError("Prediction failed")

    await worker.handle_task(
        valid_payload(),
        mocked_worker.message,
    )

    mocked_worker.message.nack.assert_awaited_once_with(requeue=True)
    mocked_worker.message.reject.assert_not_awaited()


@pytest.mark.asyncio
async def test_failure_to_complete_rejects_after_limit(mocked_worker):
    mocked_worker.start.return_value = 3
    mocked_worker.complete.side_effect = RuntimeError("Cannot save prediction")

    await worker.handle_task(
        valid_payload(),
        mocked_worker.message,
    )

    mocked_worker.predict.assert_called_once()
    mocked_worker.fail.assert_awaited_once()
    mocked_worker.message.reject.assert_awaited_once_with(requeue=False)


@pytest.mark.asyncio
async def test_health_handler():
    reader = SimpleNamespace(read=AsyncMock(return_value=b"GET /"))
    writer = SimpleNamespace(
        write=Mock(),
        drain=AsyncMock(),
        close=Mock(),
        wait_closed=AsyncMock(),
    )

    await worker.health_handler(reader, writer)

    reader.read.assert_awaited_once_with(1024)
    writer.write.assert_called_once()
    writer.drain.assert_awaited_once()
    writer.close.assert_called_once()
    writer.wait_closed.assert_awaited_once()

    assert b"200 OK" in writer.write.call_args.args[0]


@pytest.mark.asyncio
async def test_worker_startup_and_shutdown(monkeypatch):
    loaded_model = SimpleNamespace(name="test-model")

    server = SimpleNamespace(
        close=Mock(),
        wait_closed=AsyncMock(),
    )

    fake_asyncio = SimpleNamespace(
        to_thread=AsyncMock(return_value=loaded_model),
        start_server=AsyncMock(return_value=server),
    )

    create_tables = AsyncMock()
    dispose = AsyncMock()

    monkeypatch.setattr(worker, "asyncio", fake_asyncio)
    monkeypatch.setattr(worker, "create_tables", create_tables)
    monkeypatch.setattr(
        worker,
        "engine",
        SimpleNamespace(dispose=dispose),
    )

    await worker.startup()

    create_tables.assert_awaited_once()
    fake_asyncio.to_thread.assert_awaited_once_with(worker.load_price_model)
    fake_asyncio.start_server.assert_awaited_once()
    assert worker.model is loaded_model
    assert worker.health_server is server

    await worker.shutdown()

    server.close.assert_called_once()
    server.wait_closed.assert_awaited_once()
    dispose.assert_awaited_once()
    assert worker.model is None
    assert worker.health_server is None
