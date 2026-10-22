from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from rentlens import task_store


@pytest.fixture
def db(monkeypatch):
    connection = SimpleNamespace(
        execute=AsyncMock(),
        run_sync=AsyncMock(),
    )

    @asynccontextmanager
    async def connection_context():
        yield connection

    monkeypatch.setattr(
        task_store,
        "engine",
        SimpleNamespace(
            begin=connection_context,
            connect=connection_context,
        ),
    )

    return connection


@pytest.mark.asyncio
async def test_create_tables(db):
    await task_store.create_tables()

    db.execute.assert_awaited_once()
    db.run_sync.assert_awaited_once_with(task_store.metadata.create_all)

    statement = db.execute.await_args.args[0]

    assert "pg_advisory_xact_lock" in str(statement)


@pytest.mark.asyncio
async def test_record_accepted(db):
    task_id = "task-123"
    payload = {"square_feet": 900}

    await task_store.record_accepted(task_id, payload)

    db.execute.assert_awaited_once()

    statement = db.execute.await_args.args[0]
    parameters = statement.compile().params

    assert "ON CONFLICT (id) DO NOTHING" in str(statement)
    assert task_id in parameters.values()
    assert payload in parameters.values()
    assert "PENDING" in parameters.values()


@pytest.mark.asyncio
async def test_start_attempt(db):
    result = Mock()
    result.scalar_one_or_none.return_value = 1
    db.execute.return_value = result

    payload = {
        "task_id": "task-123",
        "features": {"square_feet": 900},
    }

    attempts = await task_store.start_attempt(
        "task-123",
        payload,
    )

    assert attempts == 1

    statement = db.execute.await_args.args[0]
    parameters = statement.compile().params

    assert "ON CONFLICT (id) DO UPDATE" in str(statement)
    assert {"square_feet": 900} in parameters.values()
    assert ["COMPLETED", "FAILED"] in parameters.values()


@pytest.mark.asyncio
async def test_start_attempt_already_finished(db):
    result = Mock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result

    attempts = await task_store.start_attempt(
        "task-123",
        {"square_feet": 900},
    )

    assert attempts is None


@pytest.mark.asyncio
async def test_complete(db):
    await task_store.complete("task-123", 4331.426)

    db.execute.assert_awaited_once()

    statement = db.execute.await_args.args[0]
    parameters = statement.compile().params

    assert "UPDATE prediction_tasks" in str(statement)
    assert "COMPLETED" in parameters.values()
    assert 4331.43 in parameters.values()
    assert "finished_at" in parameters


@pytest.mark.asyncio
async def test_fail_truncates_error(db):
    error = "x" * 700

    await task_store.fail("task-123", error)

    db.execute.assert_awaited_once()

    statement = db.execute.await_args.args[0]
    parameters = statement.compile().params

    assert "FAILED" in parameters.values()
    assert "x" * 500 in parameters.values()
    assert error not in parameters.values()


@pytest.mark.asyncio
async def test_get_existing_task(db):
    expected = {
        "id": "task-123",
        "status": "COMPLETED",
        "attempts": 1,
        "predicted_price": 4331.42,
    }

    result = Mock()
    result.mappings.return_value.first.return_value = expected
    db.execute.return_value = result

    task = await task_store.get_task("task-123")

    assert task == expected
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_missing_task(db):
    result = Mock()
    result.mappings.return_value.first.return_value = None
    db.execute.return_value = result

    task = await task_store.get_task("missing-task")

    assert task is None
