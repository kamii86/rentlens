FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /uvx /bin/

COPY pyproject.toml uv.lock README.md ./

RUN uv sync \
    --no-cache \
    --frozen \
    --no-dev \
    --group web \
    --no-install-project

COPY src ./src
COPY scripts/model_snapshot.py ./scripts/model_snapshot.py

RUN uv sync \
    --no-cache \
    --frozen \
    --no-dev \
    --group web

RUN useradd --create-home --uid 10001 appuser \
    && chown appuser:appuser /app

USER appuser

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["uvicorn", "rentlens.main:app", "--host", "0.0.0.0", "--port", "8000"]
