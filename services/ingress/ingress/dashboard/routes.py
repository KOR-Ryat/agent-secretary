"""Dashboard FastAPI routes.

  - GET  /              → static index.html
  - GET  /api/traces    → recent traces (list, paginated)
  - GET  /api/traces/{task_id} → full trace detail

If `DATABASE_URL` is unset (e.g. dev without Postgres), `/` still serves
the HTML but the API endpoints respond 503 — the UI displays a banner.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ingress.dashboard.traces import TraceReader
from ingress.logging import get_logger

log = get_logger("ingress.dashboard.routes")

_STATIC_DIR = Path(__file__).parent / "static"


def register_dashboard(app: FastAPI, trace_reader: TraceReader | None) -> None:
    router = APIRouter(tags=["dashboard"])

    @router.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(_STATIC_DIR / "index.html", media_type="text/html")

    @router.get("/api/traces")
    async def list_traces(
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ) -> JSONResponse:
        if trace_reader is None:
            return JSONResponse(
                {"error": "DATABASE_URL not configured"}, status_code=503
            )
        rows = await trace_reader.list_recent(limit=limit, offset=offset)
        return JSONResponse({"items": [_serialize(r) for r in rows]})

    @router.get("/api/traces/{task_id}")
    async def get_trace(task_id: str) -> JSONResponse:
        if trace_reader is None:
            return JSONResponse(
                {"error": "DATABASE_URL not configured"}, status_code=503
            )
        row = await trace_reader.get(task_id)
        if row is None:
            raise HTTPException(status_code=404, detail="trace not found")
        return JSONResponse(_serialize(row))

    app.include_router(router)
    app.mount(
        "/static",
        StaticFiles(directory=str(_STATIC_DIR)),
        name="dashboard-static",
    )


def _serialize(row: dict) -> dict:
    """Convert datetime / Decimal → JSON-friendly types."""
    out = {}
    for k, v in row.items():
        if isinstance(v, datetime):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out
