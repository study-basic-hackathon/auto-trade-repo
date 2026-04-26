FROM python:3.14.4-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY inference/pyproject.toml inference/uv.lock ./

RUN uv sync --no-install-project

ENV PATH="/app/.venv/bin:$PATH"

COPY inference/run.py ./

CMD ["python", "run.py"]
