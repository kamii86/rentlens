import json
import logging
from datetime import UTC, datetime
from typing import Any

import aio_pika
from aio_pika.exceptions import DeliveryError, PublishError

from rentlens.task_config import TaskSettings, settings

logger = logging.getLogger(__name__)


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
        if self.channel is None:
            raise RuntimeError("RabbitMQ publisher не запущен")

        body = {
            "task_id": task_id,
            "features": payload,
            "submitted_at": datetime.now(UTC).isoformat(),
        }

        message = aio_pika.Message(
            body=json.dumps(body).encode("utf-8"),
            content_type="application/json",
            message_id=task_id,
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        )

        try:
            await self.channel.default_exchange.publish(
                message,
                routing_key=self.cfg.queue_name,
                mandatory=True,
                timeout=self.cfg.publish_timeout,
            )

        except (DeliveryError, PublishError) as exc:
            raise QueueFull("RabbitMQ отклонил сообщение") from exc
