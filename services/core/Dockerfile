FROM python:3.13-slim AS base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /usr/local/bin/

COPY pyproject.toml uv.lock* ./
COPY packages/schemas packages/schemas
COPY packages/config packages/config
COPY services/core services/core
COPY services/ingress/pyproject.toml services/ingress/pyproject.toml
COPY services/agents/pyproject.toml services/agents/pyproject.toml
COPY services/egress/pyproject.toml services/egress/pyproject.toml

RUN uv sync --package agent-secretary-core --frozen --no-dev

CMD ["uv", "run", "--package", "agent-secretary-core", "python", "-m", "core.main"]
