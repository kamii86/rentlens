import asyncio
import logging
import os
import time
from asyncio import to_thread
from uuid import uuid4

from opentelemetry.context import Context

from rentlens.logging_config import configure_logging, log_context
from rentlens.metrics import pipeline
from rentlens.task_broker import QueueFull, TaskPublisher
from rentlens.telemetry import configure_telemetry, shutdown_telemetry, traced_span

logger = logging.getLogger(__name__)


async def main() -> None:
    total = int(os.getenv("BATCH_COUNT", "40"))
    if total < 1:
        raise ValueError("BATCH_COUNT must be positive")

    configure_logging()
    configure_telemetry("rentlens-source")
    publisher = TaskPublisher()
    accepted = 0
    rejected = 0
    wait_seconds = 0.0
    started = time.monotonic()
    batch_id = str(uuid4())

    with log_context(batch_id=batch_id):
        try:
            await publisher.start()
            logger.info(
                "Batch started", extra={"event": "batch_started", "total": total}
            )
            for index in range(total):
                task_id = str(uuid4())
                payload = {
                    "square_feet": 900 + index,
                    "bedrooms": 2,
                    "bathrooms": 1,
                    "latitude": 40.7128,
                    "longitude": -74.006,
                    "cityname": "New York",
                    "state": "NY",
                    "pets_allowed": "Cats,Dogs",
                }
                delay = 0.1
                attempt = 0
                with (
                    log_context(task_id=task_id),
                    traced_span(
                        "source.task",
                        context=Context(),
                        attributes={"task.id": task_id, "batch.id": batch_id},
                    ) as span,
                ):
                    while True:
                        attempt += 1
                        with log_context(publish_attempt=attempt):
                            try:
                                await publisher.publish(task_id, payload)
                                accepted += 1
                                pipeline.source_published.add(1)
                                span.set_attribute("publish.attempts", attempt)
                                logger.info(
                                    "Source task accepted",
                                    extra={"event": "source_task_accepted"},
                                )
                                break
                            except QueueFull:
                                rejected += 1
                                pipeline.source_rejected.add(1)
                                span.add_event(
                                    "publish.rejected",
                                    {
                                        "publish.attempt": attempt,
                                        "retry.delay_seconds": delay,
                                    },
                                )
                                logger.warning(
                                    "Source waiting for queue capacity",
                                    extra={
                                        "event": "source_backpressure",
                                        "delay_seconds": delay,
                                    },
                                )
                                with traced_span(
                                    "source.wait",
                                    attributes={"retry.delay_seconds": delay},
                                ):
                                    wait_started = time.monotonic()
                                    try:
                                        await asyncio.sleep(delay)
                                    finally:
                                        waited = time.monotonic() - wait_started
                                        wait_seconds += waited
                                        pipeline.source_wait.add(waited)
                                delay = min(delay * 2, 2.0)

                if accepted % 5 == 0:
                    elapsed = time.monotonic() - started
                    logger.info(
                        "Batch progress",
                        extra={
                            "event": "batch_progress",
                            "accepted": accepted,
                            "rejected": rejected,
                            "total": total,
                            "elapsed_seconds": round(elapsed, 3),
                            "rate_per_second": round(accepted / max(elapsed, 1e-9), 3),
                        },
                    )

            elapsed = time.monotonic() - started
            logger.info(
                "Batch completed",
                extra={
                    "event": "batch_completed",
                    "accepted": accepted,
                    "rejected": rejected,
                    "total": total,
                    "elapsed_seconds": round(elapsed, 3),
                    "wait_seconds": round(wait_seconds, 3),
                    "rate_per_second": round(accepted / max(elapsed, 1e-9), 3),
                },
            )
        except Exception:
            logger.exception("Batch failed", extra={"event": "batch_failed"})
            raise
        finally:
            logger.info("Source shutdown started", extra={"event": "shutdown_started"})
            try:
                await publisher.close()
            finally:
                logger.info("Source stopped", extra={"event": "shutdown_completed"})
                await to_thread(shutdown_telemetry)


if __name__ == "__main__":
    asyncio.run(main())
