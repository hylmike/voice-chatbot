# First build builder image, used for building virtual environment
FROM python:3.12-bookworm AS builder

# Install uv using the official standalone binary
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Some settings to improve build performance
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /home/backend

COPY pyproject.toml uv.lock ./
# As README file is required, use empty readme file in this step
# to avoid unnecessary layer regeneration because of readme file update
RUN touch README.md

RUN uv sync --frozen --no-dev --no-install-project

# Build runtime image, used to run as the backend
FROM python:3.12-slim-bookworm AS backend

RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

ENV VIRTUAL_ENV=/home/backend/.venv \
    PATH="/home/backend/.venv/bin:$PATH" \
    PYTHONPATH="/home/backend"

WORKDIR /home/backend

COPY --from=builder ${VIRTUAL_ENV} ${VIRTUAL_ENV}

COPY api /home/backend/api

EXPOSE 3100

CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "3100"]
