import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from rentlens import batch_source
from rentlens.task_broker import QueueFull


@pytest.fixture(autouse=True)
def disable_network_telemetry(monkeypatch):
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")


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

    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    progress = next(row for row in records if row.get("event") == "batch_progress")
    finished = next(row for row in records if row.get("event") == "batch_completed")
    assert progress["accepted"] == progress["total"] == 5
    assert finished["accepted"] == 5
    assert finished["rejected"] == 1
    assert finished["wait_seconds"] >= 0
    assert all(
        "batch_id" in row
        for row in records
        if row.get("event", "").startswith("batch_")
    )


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

    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    finished = next(row for row in records if row.get("event") == "batch_completed")
    assert finished["accepted"] == 1
    assert finished["rejected"] == 7
    rejected = [row for row in records if row.get("event") == "source_backpressure"]
    assert len(rejected) == 7
    assert [row["publish_attempt"] for row in rejected] == list(range(1, 8))
    assert len({row["task_id"] for row in rejected}) == 1


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


@pytest.mark.asyncio
async def test_each_task_has_own_trace_and_retries_keep_context(monkeypatch):
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    monkeypatch.setenv("OTEL_SDK_DISABLED", "false")
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("source-test")
    published = []

    async def publish(task_id, payload):
        context = trace.get_current_span().get_span_context()
        published.append((task_id, context.trace_id))
        if len(published) <= 2:
            raise QueueFull("Queue is full")

    publisher = SimpleNamespace(
        start=AsyncMock(),
        publish=AsyncMock(side_effect=publish),
        close=AsyncMock(),
    )
    monkeypatch.setenv("BATCH_COUNT", "3")
    monkeypatch.setattr(batch_source, "TaskPublisher", lambda: publisher)
    monkeypatch.setattr(batch_source, "asyncio", SimpleNamespace(sleep=AsyncMock()))
    monkeypatch.setattr(batch_source, "configure_telemetry", lambda name: None)
    monkeypatch.setattr(batch_source, "shutdown_telemetry", lambda: None)
    monkeypatch.setattr(batch_source, "traced_span", tracer.start_as_current_span)

    try:
        with tracer.start_as_current_span("unrelated-parent"):
            await batch_source.main()

        spans = exporter.get_finished_spans()
        roots = [span for span in spans if span.name == "source.task"]
        waits = [span for span in spans if span.name == "source.wait"]

        assert len(roots) == 3
        assert all(span.parent is None for span in roots)
        assert len({span.context.trace_id for span in roots}) == 3
        assert len(waits) == 2
        assert len({task_id for task_id, _ in published}) == 3
        assert len({trace_id for _, trace_id in published[:3]}) == 1
        assert len({trace_id for _, trace_id in published}) == 3
        assert len({span.parent.span_id for span in waits}) == 1
        assert (
            sum(
                event.name == "publish.rejected"
                for span in roots
                for event in span.events
            )
            == 2
        )
        publisher.close.assert_awaited_once()
    finally:
        provider.shutdown()


@pytest.mark.asyncio
async def test_batch_source_closes_on_startup_error(monkeypatch):
    publisher = SimpleNamespace(
        start=AsyncMock(side_effect=ConnectionError("Broker unavailable")),
        publish=AsyncMock(),
        close=AsyncMock(),
    )
    monkeypatch.setenv("BATCH_COUNT", "1")
    monkeypatch.setattr(batch_source, "TaskPublisher", lambda: publisher)

    with pytest.raises(ConnectionError, match="Broker unavailable"):
        await batch_source.main()

    publisher.close.assert_awaited_once()
    publisher.publish.assert_not_awaited()
