from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from rentlens import batch_source
from rentlens.task_broker import QueueFull


@pytest.mark.asyncio
async def test_batch_source_retries_without_losing_tasks(monkeypatch, capsys):
    published = []
    sleep = AsyncMock()

    async def publish(task_id, payload):
        published.append((task_id, payload))

        if len(published) == 1:
            raise QueueFull("Queue is full")

    publisher = SimpleNamespace(
        start=AsyncMock(),
        publish=AsyncMock(side_effect=publish),
        close=AsyncMock(),
    )

    monkeypatch.setenv("BATCH_COUNT", "5")
    monkeypatch.setattr(batch_source, "TaskPublisher", lambda: publisher)
    monkeypatch.setattr(
        batch_source,
        "asyncio",
        SimpleNamespace(sleep=sleep),
    )

    await batch_source.main()

    publisher.start.assert_awaited_once()
    publisher.close.assert_awaited_once()

    assert publisher.publish.await_count == 6
    assert published[0][0] == published[1][0]
    assert published[0][1] == published[1][1]

    assert len({task_id for task_id, _ in published}) == 5
    assert all(payload["square_feet"] >= 900 for _, payload in published)

    sleep.assert_awaited_once_with(0.1)

    output = capsys.readouterr().out
    assert "accepted=5/5" in output
    assert "FINISHED accepted=5 rejected=1" in output


@pytest.mark.asyncio
async def test_batch_source_exponential_backoff(monkeypatch, capsys):
    failures = 7
    sleep = AsyncMock()
    published_ids = []

    async def publish(task_id, payload):
        published_ids.append(task_id)

        if len(published_ids) <= failures:
            raise QueueFull("Queue is full")

    publisher = SimpleNamespace(
        start=AsyncMock(),
        publish=AsyncMock(side_effect=publish),
        close=AsyncMock(),
    )

    monkeypatch.setenv("BATCH_COUNT", "1")
    monkeypatch.setattr(batch_source, "TaskPublisher", lambda: publisher)
    monkeypatch.setattr(
        batch_source,
        "asyncio",
        SimpleNamespace(sleep=sleep),
    )

    await batch_source.main()

    delays = [call.args[0] for call in sleep.await_args_list]

    assert delays == [0.1, 0.2, 0.4, 0.8, 1.6, 2.0, 2.0]
    assert len(set(published_ids)) == 1
    assert len(published_ids) == 8

    publisher.close.assert_awaited_once()

    output = capsys.readouterr().out
    assert "FINISHED accepted=1 rejected=7" in output


@pytest.mark.asyncio
async def test_batch_source_closes_on_error(monkeypatch):
    publisher = SimpleNamespace(
        start=AsyncMock(),
        publish=AsyncMock(side_effect=RuntimeError("Broker error")),
        close=AsyncMock(),
    )

    monkeypatch.setenv("BATCH_COUNT", "1")
    monkeypatch.setattr(batch_source, "TaskPublisher", lambda: publisher)

    with pytest.raises(RuntimeError, match="Broker error"):
        await batch_source.main()

    publisher.close.assert_awaited_once()
