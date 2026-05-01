FROM python:3.13-slim AS base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /usr/local/bin/

COPY pyproject.toml uv.lock* ./
COPY packages/schemas packages/schemas
COPY packages/config packages/config
COPY services/agents services/agents
COPY services/ingress/pyproject.toml services/ingress/pyproject.toml
COPY services/core/pyproject.toml services/core/pyproject.toml
COPY services/egress/pyproject.toml services/egress/pyproject.toml

# Persona system prompts
COPY prompts prompts

RUN uv sync --package agent-secretary-agents --frozen --no-dev

CMD ["uv", "run", "--package", "agent-secretary-agents", "python", "-m", "agents.main"]
