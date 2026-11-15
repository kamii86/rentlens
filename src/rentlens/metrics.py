import math
import os
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

import psutil
from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.metrics import CallbackOptions, Meter, Observation
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
from opentelemetry.sdk.resources import Resource
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from rentlens.task_config import settings


def process_memory(_options: CallbackOptions) -> Iterator[Observation]:
    try:
        yield Observation(psutil.Process().memory_info().rss)
    except (psutil.Error, OSError):
        return


def queue_limit(_options: CallbackOptions) -> Iterator[Observation]:
    if settings.mode == "bounded":
        yield Observation(settings.queue_limit, {"queue": settings.queue_name})


class PipelineMetrics:
    def __init__(self, meter: Meter) -> None:
        self.api_requests = meter.create_counter("rentlens_api_requests", unit="1")
        self.api_duration = meter.create_histogram(
            "rentlens_api_duration_seconds", unit="s"
        )
        self.source_published = meter.create_counter(
            "rentlens_source_published", unit="1"
        )
        self.source_rejected = meter.create_counter(
            "rentlens_source_rejected", unit="1"
        )
        self.source_wait = meter.create_counter(
            "rentlens_source_wait_seconds", unit="s"
        )
        self.worker_tasks = meter.create_counter("rentlens_worker_tasks", unit="1")
        self.worker_inflight = meter.create_up_down_counter(
            "rentlens_worker_inflight", unit="1"
        )
        self.worker_duration = meter.create_histogram(
            "rentlens_worker_inference_seconds", unit="s"
        )
        self.worker_redeliveries = meter.create_counter(
            "rentlens_worker_redeliveries", unit="1"
        )
        self.worker_duplicates = meter.create_counter(
            "rentlens_worker_duplicates", unit="1"
        )
        self.memory = meter.create_observable_gauge(
            "rentlens_process_memory_bytes", callbacks=[process_memory], unit="By"
        )
        self.queue_limit = meter.create_observable_gauge(
            "rentlens_queue_limit", callbacks=[queue_limit], unit="1"
        )


def metric_views(inference_seconds: float) -> list[View]:
    if not math.isfinite(inference_seconds) or inference_seconds < 0:
        raise ValueError("INFERENCE_SECONDS must be finite and nonnegative")
    base = max(inference_seconds, 0.01)
    inference_buckets = sorted(
        {0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0}
        | {
            round(base * factor, 6)
            for factor in (0.5, 0.75, 1.0, 1.05, 1.25, 1.5, 2, 3, 5, 10)
        }
    )
    allowed = {
        "rentlens_api_requests": {"route", "method", "status_code"},
        "rentlens_api_duration_seconds": {"route", "method"},
        "rentlens_source_published": set(),
        "rentlens_source_rejected": set(),
        "rentlens_source_wait_seconds": set(),
        "rentlens_worker_tasks": {"result"},
        "rentlens_worker_inflight": set(),
        "rentlens_worker_inference_seconds": set(),
        "rentlens_worker_redeliveries": set(),
        "rentlens_worker_duplicates": set(),
        "rentlens_process_memory_bytes": set(),
        "rentlens_queue_limit": {"queue"},
    }
    views = []
    for name, keys in allowed.items():
        options = {}
        if name == "rentlens_worker_inference_seconds":
            options["aggregation"] = ExplicitBucketHistogramAggregation(
                inference_buckets
            )
        elif name == "rentlens_api_duration_seconds":
            options["aggregation"] = ExplicitBucketHistogramAggregation(
                (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10)
            )
        views.append(View(instrument_name=name, attribute_keys=keys, **options))
    return views


def create_meter_provider(
    resource: Resource,
    readers: Sequence[MetricReader],
    inference_seconds: float = settings.inference_seconds,
) -> MeterProvider:
    return MeterProvider(
        resource=resource,
        metric_readers=readers,
        views=metric_views(inference_seconds),
        shutdown_on_exit=False,
    )


def create_otlp_meter_provider(resource: Resource) -> MeterProvider | None:
    exporter_name = os.getenv("OTEL_METRICS_EXPORTER", "none")
    if exporter_name == "none":
        return None
    if exporter_name != "otlp":
        raise ValueError("OTEL_METRICS_EXPORTER must be otlp or none")
    interval = float(os.getenv("OTEL_METRIC_EXPORT_INTERVAL", "5000"))
    timeout = float(os.getenv("OTEL_METRIC_EXPORT_TIMEOUT", "1000"))
    if not all(math.isfinite(value) and value > 0 for value in (interval, timeout)):
        raise ValueError(
            "Metric export interval and timeout must be finite and positive"
        )
    reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(),
        export_interval_millis=interval,
        export_timeout_millis=timeout,
    )
    return create_meter_provider(resource, [reader])


pipeline = PipelineMetrics(metrics.get_meter("rentlens"))


@contextmanager
def track_inflight(instruments: PipelineMetrics) -> Iterator[None]:
    instruments.worker_inflight.add(1)
    try:
        yield
    finally:
        instruments.worker_inflight.add(-1)


class ApiMetricsMiddleware:
    def __init__(
        self, app: ASGIApp, instruments: PipelineMetrics | None = None
    ) -> None:
        self.app = app
        self.instruments = instruments if instruments is not None else pipeline

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        status_code = 500

        async def send_response(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_response)
        finally:
            method = scope["method"]
            if method not in {
                "GET",
                "POST",
                "PUT",
                "PATCH",
                "DELETE",
                "HEAD",
                "OPTIONS",
                "TRACE",
                "CONNECT",
            }:
                method = "OTHER"
            route = getattr(scope.get("route"), "path", None) or "unmatched"
            attributes = {"route": route, "method": method, "status_code": status_code}
            self.instruments.api_requests.add(1, attributes)
            self.instruments.api_duration.record(
                time.perf_counter() - started, attributes
            )
