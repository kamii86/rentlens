import asyncio
import os
import time
from uuid import uuid4

from rentlens.task_broker import QueueFull, TaskPublisher


async def main() -> None:
    total = int(os.getenv("BATCH_COUNT", "40"))
    publisher = TaskPublisher()

    accepted = 0
    rejected = 0
    started = time.monotonic()

    await publisher.start()

    try:
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

            while True:
                try:
                    await publisher.publish(task_id, payload)
                    accepted += 1
                    break
                except QueueFull:
                    rejected += 1
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 2.0)

            if accepted % 5 == 0:
                elapsed = time.monotonic() - started
                print(
                    f"accepted={accepted}/{total} "
                    f"rejected={rejected} "
                    f"elapsed={elapsed:.2f}s "
                    f"rate={accepted / elapsed:.2f}/s",
                    flush=True,
                )

    finally:
        await publisher.close()

    elapsed = time.monotonic() - started

    print(
        f"FINISHED accepted={accepted} rejected={rejected} elapsed={elapsed:.2f}s",
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
