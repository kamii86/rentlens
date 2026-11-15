import os

import pytest

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/test",
)


@pytest.fixture(autouse=True)
def deterministic_test_sampling(monkeypatch):
    """Проверки спанов не зависят от семплера внешнего окружения."""
    monkeypatch.setenv("OTEL_TRACES_SAMPLER", "parentbased_always_on")
    monkeypatch.setenv("OTEL_TRACES_SAMPLER_ARG", "1.0")
