import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aio_pika.exceptions import DeliveryError
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from rentlens import task_broker
from rentlens.logging_config import _log_context


@pytest.mark.asyncio
async def test_publish_propagates_w3c_context_and_uses_confirms(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider(shutdown_on_exit=False)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("publisher-test")
    monkeypatch.setattr(task_broker, "tracer", tracer)
    channel = SimpleNamespace(
        declare_exchange=AsyncMock(),
        declare_queue=AsyncMock(),
        default_exchange=SimpleNamespace(publish=AsyncMock()),
    )
    connection = SimpleNamespace(
        channel=AsyncMock(return_value=channel), close=AsyncMock()
    )
    monkeypatch.setattr(
        task_broker.aio_pika, "connect_robust", AsyncMock(return_value=connection)
    )
    publisher = task_broker.TaskPublisher()
    try:
        await publisher.start()
        connection.channel.assert_awaited_once_with(
            publisher_confirms=True, on_return_raises=True
        )
        with tracer.start_as_current_span("HTTP task") as parent:
            await publisher.publish("task-check", {"square_feet": 900})
            message = channel.default_exchange.publish.await_args.args[0]
            context = trace.get_current_span().get_span_context()
            assert context.trace_id == parent.get_span_context().trace_id
        publish_span = next(
            s for s in exporter.get_finished_spans() if s.name == "publish"
        )
        assert message.headers["traceparent"] == (
            f"00-{publish_span.context.trace_id:032x}-"
            f"{publish_span.context.span_id:016x}-{int(publish_span.context.trace_flags):02x}"
        )
        assert message.headers["task_id"] == "task-check"
        assert message.correlation_id == message.message_id == "task-check"
        body = json.loads(message.body)
        assert body["task_id"] == "task-check"
        assert body["features"] == {"square_feet": 900}
        assert body["submitted_at"].endswith("+00:00")
        assert publish_span.parent.span_id == parent.get_span_context().span_id
        assert _log_context.get() is None
        channel.declare_exchange.assert_awaited_once()
        assert channel.declare_queue.await_count == 2
    finally:
        await publisher.close()
        provider.shutdown()
    connection.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_rejected_publish_sets_error_span_and_cleans_context(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider(shutdown_on_exit=False)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(task_broker, "tracer", provider.get_tracer("publisher-test"))
    publisher = task_broker.TaskPublisher()
    publisher.channel = SimpleNamespace(
        default_exchange=SimpleNamespace(
            publish=AsyncMock(side_effect=DeliveryError(None, None))
        )
    )
    try:
        with pytest.raises(task_broker.QueueFull):
            await publisher.publish("rejected-task", {"square_feet": 900})
        span = exporter.get_finished_spans()[0]
        assert span.status.status_code == trace.StatusCode.ERROR
        assert span.events[0].attributes["exception.message"] == "DeliveryError"
        assert _log_context.get() is None
    finally:
        provider.shutdown()
