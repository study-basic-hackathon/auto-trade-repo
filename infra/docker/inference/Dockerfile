FROM python:3.14.4-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY inference/pyproject.toml inference/uv.lock ./

RUN uv sync --no-install-project

ENV PATH="/app/.venv/bin:$PATH"

COPY inference/run.py inference/run.sample.py ./

# USE_REAL_INFERENCE=true のとき run.py を、false のとき run.sample.py を entry.py として配置
ARG USE_REAL_INFERENCE=false
RUN if [ "$USE_REAL_INFERENCE" = "true" ]; then cp run.py entry.py; else cp run.sample.py entry.py; fi

CMD ["python", "entry.py"]
