"""Dashboard FastAPI routes.

  - GET  /                              → dashboard index.html
  - GET  /api/traces                    → recent traces (paginated)
  - GET  /api/traces/{task_id}          → full trace detail
  - GET  /api/stats/decisions?range=…   → decision distribution + avg conf

If `DATABASE_URL` is unset (e.g. dev without Postgres), `/` still serves
the HTML but the API endpoints respond 503 — the UI displays a banner.

The `/static/` URL prefix is intentionally NOT mounted here — it's
reserved for cross-feature served content (e.g. `/static/reports/{id}`
for rendered workflow reports — see issue #3). The dashboard SPA is
self-contained (inline styles + script) so no asset mount is needed.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

from ingress.dashboard.traces import (
    _DECISIONS,
    _RANGE_TO_INTERVAL,
    _WORKFLOWS,
    TraceReader,
)
from ingress.logging import get_logger

log = get_logger("ingress.dashboard.routes")

_INDEX_HTML = Path(__file__).parent / "index.html"


def register_dashboard(app: FastAPI, trace_reader: TraceReader | None) -> None:
    router = APIRouter(tags=["dashboard"])

    @router.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(_INDEX_HTML, media_type="text/html")

    @router.get("/api/traces")
    async def list_traces(
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        decision: str | None = Query(None),
        workflow: str | None = Query(None),
        range: str | None = Query(None),
    ) -> JSONResponse:
        if decision is not None and decision not in _DECISIONS:
            raise HTTPException(
                status_code=400, detail=f"invalid decision: {decision!r}"
            )
        if workflow is not None and workflow not in _WORKFLOWS:
            raise HTTPException(
                status_code=400, detail=f"invalid workflow: {workflow!r}"
            )
        if range is not None and range not in _RANGE_TO_INTERVAL:
            raise HTTPException(
                status_code=400, detail=f"invalid range: {range!r}"
            )
        if trace_reader is None:
            return JSONResponse(
                {"error": "DATABASE_URL not configured"}, status_code=503
            )
        rows = await trace_reader.list_recent(
            limit=limit,
            offset=offset,
            decision=decision,
            workflow=workflow,
            range_token=range,
        )
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

    @router.get("/api/stats/confidence")
    async def stats_confidence(
        range: str = Query("24h", description="One of: 1h, 6h, 24h, 7d, 30d, all"),
    ) -> JSONResponse:
        if range not in _RANGE_TO_INTERVAL:
            raise HTTPException(
                status_code=400, detail=f"invalid range: {range!r}"
            )
        if trace_reader is None:
            return JSONResponse(
                {"error": "DATABASE_URL not configured"}, status_code=503
            )
        stats = await trace_reader.stats_confidence(range)
        return JSONResponse(stats)

    @router.get("/api/stats/decisions")
    async def stats_decisions(
        range: str = Query("24h", description="One of: 1h, 6h, 24h, 7d, 30d, all"),
    ) -> JSONResponse:
        if range not in _RANGE_TO_INTERVAL:
            raise HTTPException(
                status_code=400,
                detail=f"invalid range; expected one of {sorted(_RANGE_TO_INTERVAL)}",
            )
        if trace_reader is None:
            return JSONResponse(
                {"error": "DATABASE_URL not configured"}, status_code=503
            )
        stats = await trace_reader.stats_decisions(range)
        return JSONResponse(_serialize(stats))

    app.include_router(router)


def _serialize(row: dict) -> dict:
    """Convert datetime / Decimal → JSON-friendly types."""
    out = {}
    for k, v in row.items():
        if isinstance(v, datetime):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out
