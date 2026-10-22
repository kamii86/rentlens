from dataclasses import replace
from uuid import uuid4

import pytest
from testcontainers.community.rabbitmq import RabbitMqContainer

from rentlens.task_broker import QueueFull, TaskPublisher
from rentlens.task_config import settings


@pytest.mark.asyncio
async def test_queue_overflow():
    with RabbitMqContainer(
        "rabbitmq:4.1-management",
        username="test",
        password="test",
    ) as rabbitmq:
        host = rabbitmq.get_container_host_ip()
        port = rabbitmq.get_exposed_port(5672)

        config = replace(
            settings,
            rabbitmq_url=f"amqp://test:test@{host}:{port}/",
            mode="bounded",
            queue_limit=2,
            publish_timeout=10,
        )

        publisher = TaskPublisher(config)
        await publisher.start()

        try:
            payload = {"square_feet": 900}

            await publisher.publish(str(uuid4()), payload)
            await publisher.publish(str(uuid4()), payload)

            with pytest.raises(QueueFull):
                await publisher.publish(str(uuid4()), payload)

            check_channel = await publisher.connection.channel()

            try:
                queue = await check_channel.declare_queue(
                    config.queue_name,
                    passive=True,
                )

                first = await queue.get(fail=False)
                second = await queue.get(fail=False)
                third = await queue.get(fail=False)

                assert first is not None
                assert second is not None
                assert third is None

                await first.ack()
                await second.ack()
            finally:
                await check_channel.close()

        finally:
            await publisher.close()
