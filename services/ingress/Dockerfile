FROM python:3.13-slim AS base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /usr/local/bin/

# Workspace files needed for resolution
COPY pyproject.toml uv.lock* ./
COPY packages/schemas packages/schemas
COPY services/ingress services/ingress
COPY services/core/pyproject.toml services/core/pyproject.toml
COPY services/agents/pyproject.toml services/agents/pyproject.toml
COPY services/egress/pyproject.toml services/egress/pyproject.toml

# Install only this service + its deps
RUN uv sync --package agent-secretary-ingress --frozen --no-dev

EXPOSE 8080
CMD ["uv", "run", "--package", "agent-secretary-ingress", "uvicorn", "ingress.main:app", "--host", "0.0.0.0", "--port", "8080"]
