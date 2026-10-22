from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import insert

from rentlens.database import engine

metadata = MetaData()

tasks = Table(
    "prediction_tasks",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("payload", JSON, nullable=False),
    Column("status", String(20), nullable=False),
    Column("attempts", Integer, nullable=False, default=0),
    Column("predicted_price", Float),
    Column("error", String(500)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True)),
)


def utcnow() -> datetime:
    return datetime.now(UTC)


async def create_tables() -> None:
    async with engine.begin() as conn:
        await conn.execute(text("SELECT pg_advisory_xact_lock(8374215)"))
        await conn.run_sync(metadata.create_all)


async def record_accepted(
    task_id: str,
    payload: dict[str, Any],
) -> None:
    stmt = (
        insert(tasks)
        .values(
            id=task_id,
            payload=payload,
            status="PENDING",
            attempts=0,
            created_at=utcnow(),
        )
        .on_conflict_do_nothing(index_elements=[tasks.c.id])
    )

    async with engine.begin() as conn:
        await conn.execute(stmt)


async def start_attempt(
    task_id: str,
    payload: dict[str, Any],
) -> int | None:
    stmt = (
        insert(tasks)
        .values(
            id=task_id,
            payload=payload.get("features", payload),
            status="PROCESSING",
            attempts=1,
            created_at=utcnow(),
        )
        .on_conflict_do_update(
            index_elements=[tasks.c.id],
            set_={
                "attempts": tasks.c.attempts + 1,
                "status": "PROCESSING",
            },
            where=tasks.c.status.not_in(["COMPLETED", "FAILED"]),
        )
        .returning(tasks.c.attempts)
    )

    async with engine.begin() as conn:
        result = await conn.execute(stmt)
        return result.scalar_one_or_none()


async def complete(
    task_id: str,
    predicted_price: float,
) -> None:
    stmt = (
        update(tasks)
        .where(
            tasks.c.id == task_id,
            tasks.c.status.not_in(["COMPLETED", "FAILED"]),
        )
        .values(
            status="COMPLETED",
            predicted_price=round(predicted_price, 2),
            error=None,
            finished_at=utcnow(),
        )
    )

    async with engine.begin() as conn:
        await conn.execute(stmt)


async def fail(task_id: str, error: str) -> None:
    stmt = (
        update(tasks)
        .where(
            tasks.c.id == task_id,
            tasks.c.status.not_in(["COMPLETED", "FAILED"]),
        )
        .values(
            status="FAILED",
            error=error[:500],
            finished_at=utcnow(),
        )
    )

    async with engine.begin() as conn:
        await conn.execute(stmt)


async def get_task(task_id: str) -> dict[str, Any] | None:
    async with engine.connect() as conn:
        result = await conn.execute(select(tasks).where(tasks.c.id == task_id))
        row = result.mappings().first()

        if row is None:
            return None

        return dict(row)
