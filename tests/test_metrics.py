from contextlib import contextmanager

import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import Resource

from rentlens.metrics import PipelineMetrics, create_meter_provider


@contextmanager
def measurements(inference_seconds=2.0):
    reader = InMemoryMetricReader()
    provider = create_meter_provider(
        Resource.create({"service.name": "metrics-test"}),
        [reader],
        inference_seconds=inference_seconds,
    )
    instruments = PipelineMetrics(provider.get_meter("metrics-test"))
    try:
        yield instruments, reader
    finally:
        provider.shutdown()


def snapshot(reader):
    data = reader.get_metrics_data()
    return {
        metric.name: metric
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
    }


@pytest.fixture(autouse=True)
def enable_local_metrics(monkeypatch):
    monkeypatch.setenv("OTEL_SDK_DISABLED", "false")


def test_identifiers_do_not_create_extra_series():
    with measurements() as (instruments, reader):
        instruments.source_published.add(1, {"task_id": "first", "trace_id": "aaa"})
        instruments.source_published.add(2, {"task_id": "second", "trace_id": "bbb"})
        points = snapshot(reader)["rentlens_source_published"].data.data_points
        assert len(points) == 1
        assert points[0].value == 3
        assert dict(points[0].attributes) == {}


def test_api_metrics_keep_only_bounded_labels():
    with measurements() as (instruments, reader):
        attributes = {
            "route": "/api/v1/tasks/{task_id}",
            "method": "GET",
            "status_code": 503,
            "task_id": "secret-id",
        }
        instruments.api_requests.add(1, attributes)
        instruments.api_duration.record(0.04, attributes)
        data = snapshot(reader)
        request = data["rentlens_api_requests"].data.data_points[0]
        duration = data["rentlens_api_duration_seconds"].data.data_points[0]
        assert dict(request.attributes) == {
            "route": "/api/v1/tasks/{task_id}",
            "method": "GET",
            "status_code": 503,
        }
        assert dict(duration.attributes) == {
            "route": "/api/v1/tasks/{task_id}",
            "method": "GET",
        }
        assert data["rentlens_api_requests"].data.is_monotonic
        assert duration.count == 1
        assert duration.sum == pytest.approx(0.04)


@pytest.mark.parametrize(
    ("configured", "observed", "upper_bound"),
    [(2.0, 2.04, 2.1), (10.0, 10.2, 10.5)],
)
def test_histogram_buckets_follow_inference_configuration(
    configured, observed, upper_bound
):
    with measurements(configured) as (instruments, reader):
        instruments.worker_duration.record(observed)
        point = snapshot(reader)["rentlens_worker_inference_seconds"].data.data_points[
            0
        ]
        index = point.explicit_bounds.index(upper_bound)
        assert point.bucket_counts[index] == 1
        assert point.count == 1
        assert point.sum == pytest.approx(observed)


def test_memory_and_inflight_have_gauge_semantics():
    with measurements() as (instruments, reader):
        instruments.worker_inflight.add(1)
        assert (
            snapshot(reader)["rentlens_worker_inflight"].data.data_points[0].value == 1
        )
        instruments.worker_inflight.add(-1)
        data = snapshot(reader)
        assert data["rentlens_worker_inflight"].data.data_points[0].value == 0
        assert not data["rentlens_worker_inflight"].data.is_monotonic
        assert data["rentlens_process_memory_bytes"].data.data_points[0].value > 0


@pytest.mark.asyncio
async def test_api_middleware_groups_ids_and_records_503():
    import httpx
    from fastapi import FastAPI, HTTPException

    from rentlens.metrics import ApiMetricsMiddleware

    with measurements() as (instruments, reader):
        app = FastAPI()

        @app.get("/tasks/{task_id}")
        async def task(task_id: str):
            raise HTTPException(status_code=503, detail="Unavailable")

        app.add_middleware(ApiMetricsMiddleware, instruments=instruments)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            for path in (
                "/tasks/first",
                "/tasks/second",
                "/missing-first",
                "/missing-second",
            ):
                await client.get(path)

        data = snapshot(reader)
        requests = data["rentlens_api_requests"].data.data_points
        assert len(requests) == 2
        grouped = {
            (point.attributes["route"], point.attributes["status_code"]): point.value
            for point in requests
        }
        assert grouped == {("/tasks/{task_id}", 503): 2, ("unmatched", 404): 2}
        durations = data["rentlens_api_duration_seconds"].data.data_points
        assert len(durations) == 2
        assert sum(point.count for point in durations) == 4


@pytest.mark.asyncio
async def test_worker_metrics_cover_success_dlq_retry_and_duplicate(monkeypatch):
    from dataclasses import replace
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from rentlens import worker

    with measurements() as (instruments, reader):
        monkeypatch.setattr(worker, "pipeline", instruments)
        started = AsyncMock(return_value=1)
        monkeypatch.setattr(worker, "start_attempt", started)
        monkeypatch.setattr(worker, "complete", AsyncMock())
        monkeypatch.setattr(worker, "fail", AsyncMock())
        monkeypatch.setattr(
            worker, "settings", replace(worker.settings, inference_seconds=0)
        )
        monkeypatch.setattr(
            worker,
            "model",
            SimpleNamespace(name="test", version="1", predict=lambda x: 1000.0),
        )
        message = SimpleNamespace(
            headers={},
            raw_message=SimpleNamespace(redelivered=False),
            ack=AsyncMock(),
            nack=AsyncMock(),
            reject=AsyncMock(),
        )
        await worker.handle_task(
            {"task_id": "ok", "features": {"square_feet": 900}}, message
        )
        started.return_value = 3
        await worker.handle_task({"task_id": "dlq", "features": {}}, message)
        started.return_value = 1
        monkeypatch.setattr(worker, "asyncio", SimpleNamespace(sleep=AsyncMock()))
        await worker.handle_task({"task_id": "retry", "features": {}}, message)
        started.return_value = None
        message.raw_message.redelivered = True
        await worker.handle_task({"task_id": "duplicate", "features": {}}, message)
        data = snapshot(reader)
        outcomes = {
            point.attributes["result"]: point.value
            for point in data["rentlens_worker_tasks"].data.data_points
        }
        assert outcomes == {"ok": 1, "dlq": 1, "error": 1}
        assert data["rentlens_worker_inflight"].data.data_points[0].value == 0
        assert data["rentlens_worker_inference_seconds"].data.data_points[0].count == 1
        assert data["rentlens_worker_redeliveries"].data.data_points[0].value == 1
        assert data["rentlens_worker_duplicates"].data.data_points[0].value == 1


@pytest.mark.asyncio
async def test_source_metrics_count_confirmations_rejections_and_wait(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from rentlens import batch_source
    from rentlens.task_broker import QueueFull

    with measurements() as (instruments, reader):
        publisher = SimpleNamespace(
            start=AsyncMock(),
            publish=AsyncMock(side_effect=[QueueFull("full"), None, None]),
            close=AsyncMock(),
        )
        monkeypatch.setenv("BATCH_COUNT", "2")
        monkeypatch.setattr(batch_source, "pipeline", instruments)
        monkeypatch.setattr(batch_source, "TaskPublisher", lambda: publisher)
        monkeypatch.setattr(batch_source, "asyncio", SimpleNamespace(sleep=AsyncMock()))
        monkeypatch.setattr(batch_source, "configure_telemetry", lambda name: None)
        monkeypatch.setattr(batch_source, "shutdown_telemetry", lambda: None)
        await batch_source.main()
        data = snapshot(reader)
        assert data["rentlens_source_published"].data.data_points[0].value == 2
        assert data["rentlens_source_rejected"].data.data_points[0].value == 1
        assert data["rentlens_source_wait_seconds"].data.data_points[0].value >= 0


def test_queue_limit_matches_bounded_configuration(monkeypatch):
    from dataclasses import replace

    from rentlens import metrics as module

    monkeypatch.setattr(
        module, "settings", replace(module.settings, mode="bounded", queue_limit=25)
    )
    with measurements() as (_, reader):
        point = snapshot(reader)["rentlens_queue_limit"].data.data_points[0]
        assert point.value == 25
        assert dict(point.attributes) == {"queue": "rentlens.tasks.bounded"}
