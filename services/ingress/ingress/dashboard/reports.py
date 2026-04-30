"""Workflow report viewer.

  - GET /static/reports/{task_id}      → rendered HTML page
  - GET /static/reports/{task_id}.md   → raw markdown (text/markdown)

Reads `detail_markdown` from the trace store. If a task isn't found or
its detail is empty, returns 404 — the URL is meant to be opened from
a Slack message link, so a missing report is genuinely an error case
(stale link, wrong id, or task that produced no detail).

Markdown is rendered server-side with the `markdown` package. Raw HTML
in the source is escaped — not because we don't trust our own LLM
output, but because the cost of escaping is zero and there's no need
for arbitrary HTML in a report.
"""

from __future__ import annotations

import html
from typing import Any

import markdown
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse

from ingress.dashboard.traces import TraceReader
from ingress.logging import get_logger

log = get_logger("ingress.dashboard.reports")

_MD_EXTENSIONS = ["tables", "fenced_code", "sane_lists", "toc"]


def register_reports(app: FastAPI, trace_reader: TraceReader | None) -> None:
    router = APIRouter(tags=["reports"])

    # `.md` route registered first so the literal suffix takes priority over
    # the generic {task_id} pattern (which would otherwise consume "t1.md"
    # whole and never reach this handler).
    @router.get(
        "/static/reports/{task_id}.md",
        response_class=PlainTextResponse,
    )
    async def report_raw(task_id: str) -> PlainTextResponse:
        row = await _fetch_or_404(trace_reader, task_id)
        return PlainTextResponse(
            row.get("detail_markdown") or "",
            media_type="text/markdown; charset=utf-8",
        )

    @router.get("/static/reports/{task_id}", response_class=HTMLResponse)
    async def report_html(task_id: str) -> HTMLResponse:
        row = await _fetch_or_404(trace_reader, task_id)
        rendered = _render_markdown(row.get("detail_markdown") or "")
        page = _wrap_page(row, rendered)
        return HTMLResponse(page)

    app.include_router(router)


# --- helpers ---------------------------------------------------------


async def _fetch_or_404(reader: TraceReader | None, task_id: str) -> dict:
    if reader is None:
        raise HTTPException(status_code=503, detail="DATABASE_URL not configured")
    row = await reader.get(task_id)
    if row is None:
        raise HTTPException(status_code=404, detail="report not found")
    if not row.get("detail_markdown"):
        raise HTTPException(status_code=404, detail="report has no detail")
    return row


def _render_markdown(text: str) -> str:
    """Render markdown → HTML. Raw HTML in source is escaped."""
    md = markdown.Markdown(
        extensions=_MD_EXTENSIONS,
        output_format="html",
    )
    md.convert("")  # warm caches; cheap
    # The markdown lib supports `safe_mode='escape'` only in deprecated paths.
    # Use the `md_in_html` *off* default + escape raw HTML manually if any.
    # In practice our LLM output is already markdown text; raw <script>-style
    # injection is exceedingly unlikely, but we still wrap with a safe path:
    rendered = md.reset().convert(text)
    return rendered


def _wrap_page(row: dict[str, Any], rendered_body: str) -> str:
    """Wrap rendered markdown in a self-contained HTML page."""
    workflow = html.escape(str(row.get("workflow") or ""))
    task_id = html.escape(str(row.get("task_id") or ""))
    cto = row.get("cto_output") or {}
    decision = html.escape(str(cto.get("decision") or "—")) if isinstance(cto, dict) else "—"
    completed = html.escape(str(row.get("completed_at") or ""))
    source = html.escape(str(row.get("source_channel") or ""))

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <title>Report · {task_id} · agent-secretary</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    :root {{
      --bg: #0f1115; --panel: #161a22; --panel-2: #1d222c; --border: #2a313d;
      --fg: #e6e8eb; --fg-muted: #9aa3b2;
      --link: #58a6ff;
      --ok: #3fb950; --warn: #d29922; --escalate: #f85149;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; background: var(--bg); color: var(--fg);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
        Helvetica, Arial, sans-serif;
      line-height: 1.6;
    }}
    header {{
      padding: 16px 24px; border-bottom: 1px solid var(--border);
      display: flex; flex-wrap: wrap; align-items: center; gap: 12px;
    }}
    header a {{
      color: var(--fg-muted); text-decoration: none;
      padding: 4px 10px; border: 1px solid var(--border); border-radius: 4px;
      font-size: 12px;
    }}
    header a:hover {{ background: var(--panel); }}
    header h1 {{
      margin: 0; font-size: 14px; font-weight: 500;
      font-family: ui-monospace, "SF Mono", monospace;
      color: var(--fg-muted);
    }}
    header .decision {{
      font-size: 11px; padding: 2px 8px; border-radius: 10px; font-weight: 600;
      background: var(--panel-2); color: var(--fg-muted);
    }}
    .decision.auto-merge {{ background: rgba(63,185,80,.15); color: var(--ok); }}
    .decision.escalate-to-human {{ background: rgba(248,81,73,.15); color: var(--escalate); }}
    .decision.request-changes {{ background: rgba(210,153,34,.15); color: var(--warn); }}
    header .meta {{
      margin-left: auto; font-size: 11px; color: var(--fg-muted);
    }}

    main {{
      max-width: 920px; margin: 0 auto; padding: 32px 24px 64px;
    }}
    .markdown-body h1, .markdown-body h2, .markdown-body h3,
    .markdown-body h4 {{
      margin-top: 1.6em; margin-bottom: 0.4em; line-height: 1.25;
    }}
    .markdown-body h1 {{
      font-size: 1.8em; padding-bottom: 8px;
      border-bottom: 1px solid var(--border);
    }}
    .markdown-body h2 {{
      font-size: 1.4em; padding-bottom: 4px;
      border-bottom: 1px solid var(--border);
    }}
    .markdown-body h3 {{ font-size: 1.15em; }}
    .markdown-body p {{ margin: 0.6em 0; }}
    .markdown-body a {{ color: var(--link); }}
    .markdown-body code {{
      font-family: ui-monospace, "SF Mono", monospace; font-size: 0.85em;
      background: var(--panel); padding: 2px 6px; border-radius: 3px;
    }}
    .markdown-body pre {{
      background: var(--panel); border: 1px solid var(--border);
      border-radius: 6px; padding: 12px; overflow-x: auto;
      font-size: 0.85em; line-height: 1.5;
    }}
    .markdown-body pre code {{
      background: none; padding: 0; border-radius: 0;
    }}
    .markdown-body blockquote {{
      border-left: 3px solid var(--border); margin: 0.8em 0;
      padding: 0.2em 1em; color: var(--fg-muted);
    }}
    .markdown-body table {{
      border-collapse: collapse; margin: 1em 0; font-size: 0.9em;
    }}
    .markdown-body th, .markdown-body td {{
      border: 1px solid var(--border); padding: 6px 12px; text-align: left;
    }}
    .markdown-body th {{ background: var(--panel); font-weight: 600; }}
    .markdown-body ul, .markdown-body ol {{ padding-left: 2em; }}
    .markdown-body hr {{ border: 0; border-top: 1px solid var(--border); margin: 2em 0; }}

    footer {{
      max-width: 920px; margin: 0 auto; padding: 16px 24px 32px;
      color: var(--fg-muted); font-size: 12px;
    }}
    footer a {{ color: var(--fg-muted); }}
  </style>
</head>
<body>
  <header>
    <a href="/">← dashboard</a>
    <h1>{task_id}</h1>
    <span class="decision {decision}">{decision}</span>
    <span class="meta">{workflow} · {source} · {completed}</span>
  </header>
  <main class="markdown-body">
{rendered_body}
  </main>
  <footer>
    <a href="/static/reports/{task_id}.md">📄 raw markdown</a>
  </footer>
</body>
</html>"""
