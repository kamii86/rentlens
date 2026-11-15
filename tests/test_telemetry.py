import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from rentlens import telemetry


@pytest.fixture
def isolated_telemetry(monkeypatch):
    monkeypatch.setenv("OTEL_SDK_DISABLED", "false")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "rentlens-test")
    monkeypatch.setenv(
        "OTEL_RESOURCE_ATTRIBUTES",
        "service.version=test,deployment.environment.name=test,"
        "service.instance.id=worker-test",
    )
    monkeypatch.setattr(telemetry, "_provider", None)
    monkeypatch.setattr(telemetry, "_meter_provider", None)
    monkeypatch.setattr(telemetry.trace, "set_tracer_provider", Mock())
    monkeypatch.setattr(telemetry.metrics, "set_meter_provider", Mock())
    yield
    if telemetry._provider is not None:
        telemetry._provider.shutdown()


def test_sdk_initializes_once_with_resource_and_exporters(
    isolated_telemetry, monkeypatch
):
    monkeypatch.setenv("OTEL_TRACES_EXPORTER", "otlp")
    exporter = InMemorySpanExporter()
    export_factory = Mock(return_value=exporter)
    meter = Mock()
    monkeypatch.setattr(telemetry, "OTLPSpanExporter", export_factory)
    monkeypatch.setattr(telemetry, "create_otlp_meter_provider", lambda resource: meter)

    telemetry.configure_telemetry("rentlens-test")
    telemetry.configure_telemetry("rentlens-test")
    provider = telemetry._provider
    attributes = provider.resource.attributes
    assert attributes["service.name"] == "rentlens-test"
    assert attributes["service.version"] == "test"
    assert attributes["deployment.environment.name"] == "test"
    assert attributes["service.instance.id"] == "worker-test"
    export_factory.assert_called_once()
    telemetry.trace.set_tracer_provider.assert_called_once_with(provider)
    telemetry.metrics.set_meter_provider.assert_called_once_with(meter)

    with provider.get_tracer("check").start_as_current_span("check"):
        pass
    telemetry.shutdown_telemetry()
    assert [span.name for span in exporter.get_finished_spans()] == ["check"]
    meter.force_flush.assert_called_once_with(timeout_millis=1000)
    meter.shutdown.assert_called_once_with(timeout_millis=1500)


def test_sdk_can_disable_both_exporters(isolated_telemetry, monkeypatch):
    monkeypatch.setenv("OTEL_TRACES_EXPORTER", "none")
    monkeypatch.setattr(telemetry, "create_otlp_meter_provider", lambda resource: None)
    exporter = Mock()
    monkeypatch.setattr(telemetry, "OTLPSpanExporter", exporter)
    telemetry.configure_telemetry("rentlens-test")
    assert telemetry._provider is not None
    assert telemetry._meter_provider is None
    exporter.assert_not_called()
    telemetry.metrics.set_meter_provider.assert_not_called()


def test_invalid_exporter_fails_before_provider_install(
    isolated_telemetry, monkeypatch
):
    monkeypatch.setenv("OTEL_TRACES_EXPORTER", "invalid")
    with pytest.raises(ValueError, match="OTEL_TRACES_EXPORTER"):
        telemetry.configure_telemetry("rentlens-test")
    telemetry.trace.set_tracer_provider.assert_not_called()


def test_shutdown_survives_export_and_provider_failures(
    isolated_telemetry, monkeypatch, caplog
):
    meter = Mock()
    meter.force_flush.side_effect = TimeoutError("collector offline")
    meter.shutdown.side_effect = TimeoutError("collector offline")
    provider = Mock()
    provider.shutdown.side_effect = TimeoutError("collector offline")
    monkeypatch.setattr(telemetry, "_meter_provider", meter)
    monkeypatch.setattr(telemetry, "_provider", provider)
    with caplog.at_level(logging.WARNING):
        telemetry.shutdown_telemetry()
    meter.shutdown.assert_called_once()
    provider.shutdown.assert_called_once()
    assert {record.getMessage() for record in caplog.records} >= {
        "Final metric export failed",
        "Metric shutdown failed",
        "Trace shutdown failed",
    }
    monkeypatch.setattr(telemetry, "_provider", None)


def test_error_span_keeps_type_without_input_or_credentials(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider(shutdown_on_exit=False)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(
        telemetry, "trace", SimpleNamespace(get_tracer=provider.get_tracer)
    )
    error = ValueError("private-payload postgres://user:secret@db/test")
    try:
        with pytest.raises(ValueError):
            with telemetry.traced_span("inference"):
                raise error
        span = exporter.get_finished_spans()[0]
        assert span.status.status_code == StatusCode.ERROR
        assert span.status.description == "ValueError"
        assert len(span.events) == 1
        event = span.events[0]
        assert event.attributes["exception.message"] == "ValueError"
        assert "private-payload" not in str(event.attributes)
        assert "user:secret" not in str(event.attributes)
    finally:
        provider.shutdown()
