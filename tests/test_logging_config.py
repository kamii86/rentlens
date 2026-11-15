import asyncio
import json
import logging
from types import SimpleNamespace

import pytest

from rentlens import logging_config


@pytest.mark.asyncio
async def test_context_is_isolated_between_tasks_and_cleaned_after_error():
    formatter = logging_config.JsonFormatter()

    async def task(task_id):
        try:
            with logging_config.log_context(task_id=task_id):
                await asyncio.sleep(0)
                with logging_config.log_context(attempt=2):
                    record = logging.LogRecord(
                        "check", logging.INFO, "", 0, "check", (), None
                    )
                    data = json.loads(formatter.format(record))
                    assert data["task_id"] == task_id
                    assert data["attempt"] == 2
                raise ValueError("check cleanup")
        except ValueError:
            pass
        assert logging_config._log_context.get() is None

    await asyncio.gather(task("first"), task("second"))
    assert logging_config._log_context.get() is None


@pytest.mark.parametrize(
    ("path", "status", "expected"),
    [
        ("/healthz", 200, False),
        ("/healthz?check=1", 200, False),
        ("/api/v1/health", 503, True),
        ("/api/v1/tasks", 202, True),
    ],
)
def test_health_filter_retains_errors_and_business_requests(path, status, expected):
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        "%s %s %s %s %s",
        ("client", "GET", path, "1.1", status),
        None,
    )
    assert logging_config.HealthCheckFilter().filter(record) == expected


def test_health_filter_accepts_unknown_access_format():
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, "check", (), None)
    assert logging_config.HealthCheckFilter().filter(record)


def test_json_redacts_dsn_and_uses_sdk_identity(monkeypatch):
    resource = SimpleNamespace(
        attributes={
            "service.name": "rentlens-worker",
            "service.instance.id": "worker-2",
            "deployment.environment.name": "test",
        }
    )
    monkeypatch.setattr(
        logging_config.trace,
        "get_tracer_provider",
        lambda: SimpleNamespace(resource=resource),
    )
    record = logging.LogRecord(
        "check",
        logging.ERROR,
        "",
        0,
        "Connection amqp://user:secret@rabbitmq/",
        (),
        None,
    )
    record.event = "connection_failed"
    record.payload = "private-input"
    result = json.loads(logging_config.JsonFormatter().format(record))
    assert result["instance"] == "worker-2"
    assert result["service"] == "rentlens-worker"
    assert result["env"] == "test"
    assert result["event"] == "connection_failed"
    assert "user:secret" not in result["message"]
    assert "payload" not in result


def test_invalid_log_level_is_rejected(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "wrong")
    with pytest.raises(ValueError, match="Invalid LOG_LEVEL"):
        logging_config.configure_logging()
