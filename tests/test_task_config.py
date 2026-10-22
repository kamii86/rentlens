from dataclasses import replace

import pytest

from rentlens.task_config import TaskSettings


@pytest.mark.parametrize(
    "changes",
    [
        {"mode": "invalid"},
        {"queue_limit": 0},
        {"prefetch_count": 0},
        {"worker_concurrency": 0},
        {"inference_seconds": -1},
        {"max_attempts": 0},
    ],
)
def test_invalid_settings(changes):
    with pytest.raises(ValueError):
        TaskSettings(**changes)


def test_bounded_queue():
    config = TaskSettings(
        mode="bounded",
        queue_limit=10,
        inference_seconds=5,
        worker_concurrency=2,
    )

    assert config.queue_name == "rentlens.tasks.bounded"
    assert config.queue_arguments["x-max-length"] == 10
    assert config.queue_arguments["x-overflow"] == "reject-publish"
    assert config.queue_arguments["x-dead-letter-exchange"] == "rentlens.dlx"
    assert config.retry_after == 3


def test_unbounded_queue():
    config = TaskSettings(mode="unbounded")

    assert config.queue_name == "rentlens.tasks.unbounded"
    assert "x-max-length" not in config.queue_arguments
    assert "x-overflow" not in config.queue_arguments
    assert config.queue_arguments["x-dead-letter-routing-key"] == "rentlens.failed"


def test_minimum_retry_after():
    config = TaskSettings(
        inference_seconds=0,
        worker_concurrency=4,
    )

    assert config.retry_after == 1


def test_reconfigure_settings():
    original = TaskSettings(mode="bounded", queue_limit=10)
    modified = replace(original, queue_limit=2)

    assert original.queue_limit == 10
    assert modified.queue_limit == 2
    assert modified.queue_arguments["x-max-length"] == 2
