import asyncio
import logging
from typing import Any

from faststream import AckPolicy, FastStream
from faststream.rabbit import RabbitBroker, RabbitQueue
from faststream.rabbit.annotations import RabbitMessage
from faststream.rabbit.schemas import Channel

from rentlens.api.process import (
    ApartmentInput,
    LoadedPriceModel,
    load_price_model,
)
from rentlens.database import engine
from rentlens.task_config import settings
from rentlens.task_store import (
    complete,
    create_tables,
    fail,
    start_attempt,
)

logger = logging.getLogger(__name__)

broker = RabbitBroker(
    settings.rabbitmq_url,
    default_channel=Channel(
        prefetch_count=settings.prefetch_count,
    ),
    graceful_timeout=settings.graceful_timeout,
)

app = FastStream(broker)

model: LoadedPriceModel | None = None
health_server: asyncio.AbstractServer | None = None
execution_slots = asyncio.Semaphore(settings.worker_concurrency)


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

    await create_tables()
    model = await asyncio.to_thread(load_price_model)

    health_server = await asyncio.start_server(
        health_handler,
        "0.0.0.0",
        settings.worker_health_port,
    )

    logger.info(
        "Worker started: model=%s, prefetch=%s",
        model.name,
        settings.prefetch_count,
    )


@app.after_shutdown
async def shutdown() -> None:
    global model, health_server

    if health_server is not None:
        health_server.close()
        await health_server.wait_closed()
        health_server = None

    model = None
    await engine.dispose()


@broker.subscriber(
    RabbitQueue(
        settings.queue_name,
        durable=True,
        arguments=settings.queue_arguments,
    ),
    ack_policy=AckPolicy.MANUAL,
)
async def handle_task(
    payload: dict[str, Any],
    msg: RabbitMessage,
) -> None:
    task_id = payload.get("task_id")
    features = payload.get("features")

    if not isinstance(task_id, str) or not task_id:
        await msg.reject(requeue=False)
        return

    if not isinstance(features, dict):
        await msg.reject(requeue=False)
        return

    try:
        attempts = await start_attempt(task_id, payload)
    except Exception:
        logger.exception("Failed to start task %s", task_id)
        await msg.nack(requeue=True)
        return

    if attempts is None:
        await msg.ack()
        return

    try:
        apartment = ApartmentInput.model_validate(features)

        if model is None:
            raise RuntimeError("Model is not loaded")

        async with execution_slots:
            await asyncio.sleep(settings.inference_seconds)
            price = await asyncio.to_thread(
                model.predict,
                apartment,
            )

        await complete(task_id, price)

    except Exception as error:
        logger.exception("Task %s failed", task_id)

        if attempts >= settings.max_attempts:
            try:
                await fail(task_id, str(error))
            except Exception:
                logger.exception("Failed to save task error")
                await msg.nack(requeue=True)
                return

            await msg.reject(requeue=False)
            return

        await asyncio.sleep(min(2 ** (attempts - 1), 8))
        await msg.nack(requeue=True)
        return

    await msg.ack()
    logger.info("Task %s completed", task_id)
