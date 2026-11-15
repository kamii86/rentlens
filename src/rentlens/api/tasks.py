import logging
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request, status
from opentelemetry import propagate, trace
from opentelemetry.trace import SpanKind
from pydantic import BaseModel

from rentlens.api.process import ApartmentInput
from rentlens.logging_config import log_context
from rentlens.task_broker import QueueFull
from rentlens.task_config import settings
from rentlens.task_store import get_task, record_accepted
from rentlens.telemetry import record_error

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])
logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class AcceptedTask(BaseModel):
    task_id: UUID
    status: str
    status_url: str


@router.post(
    "",
    response_model=AcceptedTask,
    status_code=status.HTTP_202_ACCEPTED,
)
async def enqueue_task(
    apartment: ApartmentInput,
    request: Request,
) -> AcceptedTask:
    task_id = str(uuid4())
    payload = apartment.model_dump()

    with (
        log_context(task_id=task_id),
        tracer.start_as_current_span(
            "POST /api/v1/tasks",
            context=propagate.extract(dict(request.headers)),
            kind=SpanKind.SERVER,
            attributes={
                "http.request.method": "POST",
                "http.route": "/api/v1/tasks",
                "task.id": task_id,
            },
            record_exception=False,
            set_status_on_exception=False,
        ) as span,
    ):
        logger.info(
            "Task received",
            extra={"event": "task_received"},
        )

        try:
            await request.app.state.publisher.publish(task_id, payload)
        except QueueFull as error:
            record_error(span, error)
            span.set_attribute("http.response.status_code", 503)

            logger.warning(
                "Queue is full",
                extra={"event": "api_overloaded"},
            )

            raise HTTPException(
                status_code=503,
                detail="Очередь заполнена",
                headers={"Retry-After": str(settings.retry_after)},
            ) from error
        except Exception as error:
            record_error(span, error)
            span.set_attribute("http.response.status_code", 503)

            logger.exception(
                "Broker is unavailable",
                extra={"event": "api_publish_failed"},
            )

            raise HTTPException(
                status_code=503,
                detail="Брокер временно недоступен",
                headers={"Retry-After": str(settings.retry_after)},
            ) from error

        try:
            with tracer.start_as_current_span(
                "db.record_accepted",
                kind=SpanKind.CLIENT,
                attributes={"db.system.name": "postgresql"},
                record_exception=False,
                set_status_on_exception=False,
            ) as db_span:
                try:
                    await record_accepted(task_id, payload)
                except Exception as error:
                    record_error(db_span, error)
                    raise
        except Exception as error:
            record_error(span, error)
            span.set_attribute("http.response.status_code", 500)

            logger.exception(
                "Failed to record accepted task",
                extra={"event": "task_registration_failed"},
            )

            raise HTTPException(
                status_code=500,
                detail="Не удалось зарегистрировать задачу",
            ) from error

        span.set_attribute("http.response.status_code", 202)

        logger.info(
            "Task accepted",
            extra={"event": "task_accepted"},
        )

        return AcceptedTask(
            task_id=task_id,
            status="ACCEPTED",
            status_url=f"/api/v1/tasks/{task_id}",
        )


@router.get("/{task_id}")
async def task_status(task_id: UUID) -> dict:
    task = await get_task(str(task_id))

    if task is None:
        raise HTTPException(
            status_code=404,
            detail="Задача не найдена",
        )

    return {
        "task_id": task["id"],
        "status": task["status"],
        "attempts": task["attempts"],
        "predicted_price": task["predicted_price"],
        "currency": "USD",
        "error": task["error"],
        "created_at": task["created_at"],
        "finished_at": task["finished_at"],
    }
