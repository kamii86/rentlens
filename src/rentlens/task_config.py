import math
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class TaskSettings:
    rabbitmq_url: str = os.getenv(
        "RABBITMQ_URL",
        "amqp://guest:guest@127.0.0.1:5672/",
    )

    mode: str = os.getenv("QUEUE_MODE", "bounded")
    queue_limit: int = int(os.getenv("QUEUE_LIMIT", "10"))

    inference_seconds: float = float(os.getenv("INFERENCE_SECONDS", "2.0"))

    prefetch_count: int = int(os.getenv("PREFETCH_COUNT", "1"))

    worker_concurrency: int = int(os.getenv("WORKER_CONCURRENCY", "1"))

    max_attempts: int = int(os.getenv("MAX_ATTEMPTS", "3"))

    publish_timeout: float = float(os.getenv("PUBLISH_TIMEOUT", "1.0"))

    graceful_timeout: float = float(os.getenv("GRACEFUL_TIMEOUT", "40"))

    worker_health_port: int = int(os.getenv("WORKER_HEALTH_PORT", "9000"))

    def __post_init__(self):
        if self.mode not in {"bounded", "unbounded"}:
            raise ValueError("Invalid queue mode")

        if self.queue_limit < 1:
            raise ValueError("Queue limit must be positive")

        if self.prefetch_count < 1:
            raise ValueError("Prefetch must be positive")

        if self.worker_concurrency < 1:
            raise ValueError("Concurrency must be positive")

        if self.inference_seconds < 0:
            raise ValueError("Inference time cannot be negative")

        if self.max_attempts < 1:
            raise ValueError("Max attempts must be positive")

    @property
    def queue_name(self) -> str:
        return f"rentlens.tasks.{self.mode}"

    @property
    def retry_after(self) -> int:
        return max(
            1,
            math.ceil(self.inference_seconds / self.worker_concurrency),
        )

    @property
    def queue_arguments(self) -> dict:
        arguments = {
            "x-dead-letter-exchange": "rentlens.dlx",
            "x-dead-letter-routing-key": "rentlens.failed",
        }

        if self.mode == "bounded":
            arguments.update(
                {
                    "x-max-length": self.queue_limit,
                    "x-overflow": "reject-publish",
                }
            )

        return arguments


settings = TaskSettings()
