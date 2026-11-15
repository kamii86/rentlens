import json
import logging
from datetime import UTC, datetime
from typing import Any

import aio_pika
from aio_pika.exceptions import DeliveryError, PublishError
from opentelemetry import propagate, trace
from opentelemetry.trace import SpanKind

from rentlens.logging_config import log_context
from rentlens.task_config import TaskSettings, settings
from rentlens.telemetry import record_error

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class QueueFull(Exception):
    """RabbitMQ отклонил публикацию сообщения."""


async def declare_topology(
    channel: aio_pika.abc.AbstractChannel,
    cfg: TaskSettings,
) -> None:
    dlx = await channel.declare_exchange(
        "rentlens.dlx",
        aio_pika.ExchangeType.DIRECT,
        durable=True,
    )

    dlq = await channel.declare_queue(
        "rentlens.dlq",
        durable=True,
        arguments={"x-queue-type": "classic"},
    )

    await dlq.bind(dlx, routing_key="rentlens.failed")

    await channel.declare_queue(
        cfg.queue_name,
        durable=True,
        arguments={
            "x-queue-type": "classic",
            **cfg.queue_arguments,
        },
    )


class TaskPublisher:
    def __init__(
        self,
        cfg: TaskSettings = settings,
    ) -> None:
        self.cfg = cfg
        self.connection = None
        self.channel = None

    async def start(self) -> None:
        self.connection = await aio_pika.connect_robust(self.cfg.rabbitmq_url)

        self.channel = await self.connection.channel(
            publisher_confirms=True,
            on_return_raises=True,
        )

        await declare_topology(self.channel, self.cfg)

    async def close(self) -> None:
        if self.connection is not None:
            await self.connection.close()

    async def publish(
        self,
        task_id: str,
        payload: dict[str, Any],
    ) -> None:
        with (
            log_context(task_id=task_id),
            tracer.start_as_current_span(
                "publish",
                kind=SpanKind.PRODUCER,
                attributes={
                    "messaging.system": "rabbitmq",
                    "messaging.destination.name": self.cfg.queue_name,
                    "messaging.operation.name": "publish",
                    "messaging.message.id": task_id,
                },
                record_exception=False,
                set_status_on_exception=False,
            ) as span,
        ):
            try:
                if self.channel is None:
                    raise RuntimeError("RabbitMQ publisher не запущен")

                body = {
                    "task_id": task_id,
                    "features": payload,
                    "submitted_at": datetime.now(UTC).isoformat(),
                }

                headers: dict[str, Any] = {"task_id": task_id}
                propagate.inject(headers)

                message = aio_pika.Message(
                    body=json.dumps(body).encode("utf-8"),
                    content_type="application/json",
                    message_id=task_id,
                    correlation_id=task_id,
                    headers=headers,
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                )

                await self.channel.default_exchange.publish(
                    message,
                    routing_key=self.cfg.queue_name,
                    mandatory=True,
                    timeout=self.cfg.publish_timeout,
                )

            except (DeliveryError, PublishError) as error:
                record_error(span, error)

                logger.warning(
                    "Broker rejected publication",
                    extra={
                        "event": "publish_rejected",
                        "queue": self.cfg.queue_name,
                    },
                )

                raise QueueFull("RabbitMQ отклонил сообщение") from error

            except Exception as error:
                record_error(span, error)

                logger.exception(
                    "Task publication failed",
                    extra={
                        "event": "publish_failed",
                        "queue": self.cfg.queue_name,
                    },
                )
                raise

            logger.info(
                "Task published",
                extra={
                    "event": "task_published",
                    "queue": self.cfg.queue_name,
                },
            )
