import logging
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from rentlens.api.process import ApartmentInput
from rentlens.task_broker import QueueFull
from rentlens.task_config import settings
from rentlens.task_store import get_task, record_accepted

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])
logger = logging.getLogger(__name__)


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

    try:
        await request.app.state.publisher.publish(
            task_id,
            payload,
        )
    except QueueFull as exc:
        raise HTTPException(
            status_code=503,
            detail="Очередь заполнена",
            headers={"Retry-After": str(settings.retry_after)},
        ) from exc
    except Exception as exc:
        logger.exception("Ошибка публикации задачи")
        raise HTTPException(
            status_code=503,
            detail="Брокер временно недоступен",
            headers={"Retry-After": str(settings.retry_after)},
        ) from exc

    await record_accepted(task_id, payload)

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
