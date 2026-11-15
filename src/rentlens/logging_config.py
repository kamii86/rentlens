import json
import logging
import os
import re
import socket
import sys
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime

from opentelemetry import trace

_log_context: ContextVar[dict[str, str | int] | None] = ContextVar(
    "log_context",
    default=None,
)

_credentials = re.compile(r"([a-zA-Z][a-zA-Z0-9+.-]*://)[^/\s@]+@")

_extra_fields = (
    "event",
    "model_name",
    "model_alias",
    "model_version",
    "queue",
    "prefetch_count",
    "delay_seconds",
    "accepted",
    "rejected",
    "total",
    "elapsed_seconds",
    "rate_per_second",
    "wait_seconds",
)


def redact(value: str) -> str:
    """Скрывает имя пользователя и пароль в URL подключения."""
    return _credentials.sub(r"\1***@", value)


@contextmanager
def log_context(**fields: str | int | None) -> Iterator[None]:
    """Добавляет поля ко всем логам внутри блока."""
    current = dict(_log_context.get() or {})
    current.update({key: value for key, value in fields.items() if value is not None})

    token = _log_context.set(current)

    try:
        yield
    finally:
        _log_context.reset(token)


class HealthCheckFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != "uvicorn.access":
            return True

        args = record.args

        if not isinstance(args, tuple) or len(args) < 5:
            return True

        path = str(args[2]).split("?", maxsplit=1)[0]
        status_code = int(args[4])

        health_paths = {"/healthz", "/api/v1/health", "/metrics"}

        return path not in health_paths or status_code >= 400


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        resource = getattr(trace.get_tracer_provider(), "resource", None)
        attributes = getattr(resource, "attributes", {})
        entry = {
            "timestamp": datetime.fromtimestamp(
                record.created,
                tz=UTC,
            ).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "service": attributes.get(
                "service.name", os.getenv("OTEL_SERVICE_NAME", "rentlens")
            ),
            "env": attributes.get(
                "deployment.environment.name",
                os.getenv("DEPLOYMENT_ENVIRONMENT", "local"),
            ),
            "instance": attributes.get("service.instance.id", socket.gethostname()),
            "logger": record.name,
            "message": redact(record.getMessage()),
        }

        entry.update(_log_context.get() or {})

        for field in _extra_fields:
            value = getattr(record, field, None)

            if value is not None:
                entry[field] = redact(value) if isinstance(value, str) else value

        span_context = trace.get_current_span().get_span_context()

        if span_context.is_valid:
            entry["trace_id"] = f"{span_context.trace_id:032x}"
            entry["span_id"] = f"{span_context.span_id:016x}"

        if record.exc_info and record.exc_info[0] is not None:
            entry["exception_type"] = record.exc_info[0].__name__

            # Сохраняем стек без значений переменных и тела записи.
            entry["stacktrace"] = redact(
                "".join(traceback.format_tb(record.exc_info[2]))
            )

        return json.dumps(entry, ensure_ascii=False, default=str)


def configure_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, None)

    if not isinstance(level, int):
        raise ValueError(f"Invalid LOG_LEVEL: {level_name}")

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(HealthCheckFilter())

    logging.basicConfig(
        level=level,
        handlers=[handler],
        force=True,
    )

    # Библиотеки используют общий обработчик и формат.
    for name in (
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "faststream",
        "aio_pika",
        "aiormq",
    ):
        library_logger = logging.getLogger(name)
        library_logger.handlers.clear()
        library_logger.propagate = True
        library_logger.setLevel(logging.NOTSET)
