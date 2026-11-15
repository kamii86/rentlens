import logging
import os
import socket
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span, Status, StatusCode

from rentlens.logging_config import redact
from rentlens.metrics import create_otlp_meter_provider
from rentlens.version import __version__

logger = logging.getLogger(__name__)
_provider: TracerProvider | None = None
_meter_provider: MeterProvider | None = None


def configure_telemetry(service_name: str) -> None:
    global _provider, _meter_provider

    os.environ.setdefault("OTEL_SERVICE_NAME", service_name)

    if os.getenv("OTEL_SDK_DISABLED", "true").lower() == "true":
        logger.info(
            "Telemetry disabled",
            extra={"event": "telemetry_disabled"},
        )
        return

    if _provider is not None:
        return

    exporter_name = os.getenv("OTEL_TRACES_EXPORTER", "otlp")

    if exporter_name not in {"otlp", "none"}:
        raise ValueError("OTEL_TRACES_EXPORTER must be otlp or none")

    os.environ.setdefault("OTEL_EXPORTER_OTLP_TIMEOUT", "1")
    os.environ.setdefault("OTEL_BSP_MAX_QUEUE_SIZE", "512")
    os.environ.setdefault("OTEL_BSP_MAX_EXPORT_BATCH_SIZE", "128")
    os.environ.setdefault("OTEL_BSP_SCHEDULE_DELAY", "1000")

    attributes = dict(Resource.create().attributes)
    attributes.setdefault("service.version", __version__)
    attributes.setdefault("deployment.environment.name", "local")
    attributes.setdefault("service.instance.id", socket.gethostname())

    resource = Resource(attributes)
    meter_provider = create_otlp_meter_provider(resource)
    provider = TracerProvider(resource=resource)

    if exporter_name == "otlp":
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))

    trace.set_tracer_provider(provider)
    _provider = provider
    if meter_provider is not None:
        metrics.set_meter_provider(meter_provider)
    _meter_provider = meter_provider

    logger.info(
        "Telemetry initialized",
        extra={"event": "telemetry_initialized"},
    )


def record_error(span: Span, error: Exception) -> None:
    """Сохраняет ошибку без значений входных данных и паролей."""
    error_type = type(error).__name__
    stack = redact("".join(traceback.format_tb(error.__traceback__)))

    span.record_exception(
        error,
        attributes={
            "exception.message": error_type,
            "exception.stacktrace": stack,
        },
    )
    span.set_status(Status(StatusCode.ERROR, error_type))


def shutdown_telemetry() -> None:
    if _meter_provider is not None:
        try:
            _meter_provider.force_flush(timeout_millis=1000)
        except Exception:
            logger.warning("Final metric export failed", exc_info=True)
        try:
            _meter_provider.shutdown(timeout_millis=1500)
        except Exception:
            logger.warning("Metric shutdown failed", exc_info=True)
    if _provider is not None:
        try:
            _provider.shutdown()
        except Exception:
            logger.warning("Trace shutdown failed", exc_info=True)


@contextmanager
def traced_span(name: str, **options: Any) -> Iterator[Span]:
    with trace.get_tracer("rentlens").start_as_current_span(
        name,
        record_exception=False,
        set_status_on_exception=False,
        **options,
    ) as span:
        try:
            yield span
        except Exception as error:
            record_error(span, error)
            raise
