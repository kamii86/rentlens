import asyncio
import logging
import os
import time
from contextvars import copy_context
from datetime import datetime
from typing import Any

from faststream import AckPolicy, FastStream
from faststream.rabbit import RabbitBroker, RabbitQueue
from faststream.rabbit.annotations import RabbitMessage
from faststream.rabbit.schemas import Channel
from opentelemetry import propagate, trace
from opentelemetry.trace import SpanKind

from rentlens.api.process import ApartmentInput, LoadedPriceModel, load_price_model
from rentlens.database import engine
from rentlens.logging_config import configure_logging, log_context
from rentlens.metrics import pipeline, track_inflight
from rentlens.task_config import settings
from rentlens.task_store import complete, create_tables, fail, start_attempt
from rentlens.telemetry import (
    configure_telemetry,
    record_error,
    shutdown_telemetry,
    traced_span,
)

os.environ.setdefault("OTEL_SERVICE_NAME", "rentlens-worker")
configure_logging()
logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

broker = RabbitBroker(
    settings.rabbitmq_url,
    default_channel=Channel(prefetch_count=settings.prefetch_count),
    graceful_timeout=settings.graceful_timeout,
    logger=logger,
)
app = FastStream(broker, logger=logger)

model: LoadedPriceModel | None = None
health_server: asyncio.AbstractServer | None = None
execution_slots = asyncio.Semaphore(settings.worker_concurrency)


def model_attributes(loaded: LoadedPriceModel) -> dict[str, str]:
    return {
        "model.name": getattr(loaded, "name", "unknown"),
        "model.version": getattr(loaded, "version", "unknown"),
        "model.alias": os.getenv("MLFLOW_MODEL_ALIAS", "champion"),
    }


def predict_in_span(loaded: LoadedPriceModel, apartment: ApartmentInput) -> float:
    with traced_span("inference", attributes=model_attributes(loaded)):
        started = time.perf_counter()
        try:
            time.sleep(settings.inference_seconds)
            price = loaded.predict(apartment)
            logger.info("Inference completed", extra={"event": "inference_completed"})
            return price
        finally:
            pipeline.worker_duration.record(time.perf_counter() - started)


async def health_handler(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    try:
        await reader.read(1024)
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK"
        )
        await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()


@app.on_startup
async def startup() -> None:
    global model, health_server

    configure_logging()
    configure_telemetry("rentlens-worker")
    await create_tables()

    with traced_span("model.load"):
        model = await asyncio.to_thread(load_price_model)
        logger.info(
            "Worker model loaded",
            extra={
                "event": "model_loaded",
                "model_name": model.name,
                "model_version": getattr(model, "version", "unknown"),
                "model_alias": os.getenv("MLFLOW_MODEL_ALIAS", "champion"),
                "prefetch_count": settings.prefetch_count,
            },
        )

    health_server = await asyncio.start_server(
        health_handler, "0.0.0.0", settings.worker_health_port
    )
    logger.info("Worker ready", extra={"event": "startup_completed"})


@app.on_shutdown
async def begin_shutdown() -> None:
    logger.info("Worker shutdown started", extra={"event": "shutdown_started"})


@app.after_shutdown
async def shutdown() -> None:
    global model, health_server

    try:
        if health_server is not None:
            health_server.close()
            await health_server.wait_closed()
            health_server = None

        model = None
        await engine.dispose()
        logger.info("Worker stopped", extra={"event": "shutdown_completed"})
    finally:
        await asyncio.to_thread(shutdown_telemetry)


def record_queue_wait(payload: dict[str, Any], headers: dict, received_ns: int) -> None:
    submitted = payload.get("submitted_at")
    if not isinstance(submitted, str):
        return
    try:
        timestamp = datetime.fromisoformat(submitted)
        if timestamp.tzinfo is None:
            return
        started_ns = int(timestamp.timestamp() * 1_000_000_000)
    except (ValueError, OverflowError):
        return
    if started_ns > received_ns:
        return
    span = tracer.start_span(
        "queue.wait",
        context=propagate.extract(headers),
        start_time=started_ns,
        attributes={
            "messaging.destination.name": settings.queue_name,
            "queue.wait_seconds": (received_ns - started_ns) / 1_000_000_000,
        },
    )
    span.end(end_time=received_ns)


async def dead_letter(msg: RabbitMessage, error: Exception) -> None:
    with traced_span(
        "message.dead_letter",
        attributes={"messaging.destination.name": "rentlens.dlq"},
    ) as span:
        record_error(span, error)
        await msg.reject(requeue=False)
        pipeline.worker_tasks.add(1, {"result": "dlq"})
        logger.error("Task sent to DLQ", extra={"event": "task_dlq"})


async def process_attempt(
    task_id: str,
    features: dict[str, Any],
    attempts: int,
    msg: RabbitMessage,
    span: trace.Span,
) -> None:
    try:
        apartment = ApartmentInput.model_validate(features)
        loaded = model
        if loaded is None:
            raise RuntimeError("Model is not loaded")

        async with execution_slots:
            context = copy_context()
            price = await asyncio.get_running_loop().run_in_executor(
                None, context.run, predict_in_span, loaded, apartment
            )

        with traced_span(
            "db.complete",
            kind=SpanKind.CLIENT,
            attributes={"db.system.name": "postgresql"},
        ):
            await complete(task_id, price)

    except Exception as error:
        record_error(span, error)
        logger.exception("Task failed", extra={"event": "task_failed"})

        if attempts >= settings.max_attempts:
            try:
                with traced_span(
                    "db.fail",
                    kind=SpanKind.CLIENT,
                    attributes={"db.system.name": "postgresql"},
                ):
                    await fail(task_id, str(error))
            except Exception as store_error:
                record_error(span, store_error)
                logger.exception(
                    "Failed to save task error",
                    extra={"event": "task_error_save_failed"},
                )
                await msg.nack(requeue=True)
                pipeline.worker_tasks.add(1, {"result": "error"})
                span.add_event("message.requeued", {"reason": "database_error"})
                return
            await dead_letter(msg, error)
            return

        delay = min(2 ** (attempts - 1), 8)
        logger.warning(
            "Task will be retried",
            extra={"event": "task_retry", "delay_seconds": delay},
        )
        with traced_span("retry.wait", attributes={"retry.delay_seconds": delay}):
            await asyncio.sleep(delay)
        await msg.nack(requeue=True)
        pipeline.worker_tasks.add(1, {"result": "error"})
        span.add_event("message.requeued", {"task.attempt": attempts})
        return

    await msg.ack()
    pipeline.worker_tasks.add(1, {"result": "ok"})
    span.add_event("message.acked")
    logger.info("Task completed", extra={"event": "task_completed"})


@broker.subscriber(
    RabbitQueue(settings.queue_name, durable=True, arguments=settings.queue_arguments),
    ack_policy=AckPolicy.MANUAL,
)
async def handle_task(payload: dict[str, Any], msg: RabbitMessage) -> None:
    received_ns = time.time_ns()
    headers = getattr(msg, "headers", None) or {}
    task_id = payload.get("task_id")
    features = payload.get("features")

    with (
        track_inflight(pipeline),
        log_context(task_id=task_id if isinstance(task_id, str) else None),
        traced_span(
            "process",
            context=propagate.extract(headers),
            kind=SpanKind.CONSUMER,
            attributes={
                "messaging.system": "rabbitmq",
                "messaging.destination.name": settings.queue_name,
                "messaging.operation.name": "process",
            },
        ) as span,
    ):
        raw_message = getattr(msg, "raw_message", None)
        redelivered = bool(getattr(raw_message, "redelivered", False))
        if redelivered:
            pipeline.worker_redeliveries.add(1)

        if not isinstance(task_id, str) or not task_id:
            error = ValueError("Message has no task_id")
            record_error(span, error)
            await dead_letter(msg, error)
            return

        span.set_attribute("task.id", task_id)
        logger.info("Task processing started", extra={"event": "task_started"})

        if not isinstance(features, dict):
            error = ValueError("Message features must be an object")
            record_error(span, error)
            await dead_letter(msg, error)
            return

        try:
            with traced_span(
                "db.start_attempt",
                kind=SpanKind.CLIENT,
                attributes={"db.system.name": "postgresql"},
            ):
                attempts = await start_attempt(task_id, payload)
        except Exception as error:
            record_error(span, error)
            logger.exception(
                "Failed to start task", extra={"event": "task_start_failed"}
            )
            await msg.nack(requeue=True)
            pipeline.worker_tasks.add(1, {"result": "error"})
            span.add_event("message.requeued", {"reason": "database_error"})
            return

        if attempts is None:
            await msg.ack()
            pipeline.worker_duplicates.add(1)
            span.add_event("message.acked", {"reason": "already_terminal"})
            logger.info("Duplicate skipped", extra={"event": "task_duplicate"})
            return

        span.set_attribute("task.attempt", attempts)
        span.set_attribute("messaging.message.redelivered", redelivered)
        if attempts == 1 and not redelivered:
            record_queue_wait(payload, headers, received_ns)

        with log_context(attempt=attempts):
            await process_attempt(task_id, features, attempts, msg, span)
