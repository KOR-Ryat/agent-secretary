from datetime import datetime

from pydantic import BaseModel

from agent_secretary_schemas.events import ResponseRouting


class ResultEvent(BaseModel):
    result_id: str
    task_id: str
    event_id: str
    workflow: str
    output: dict
    summary_markdown: str
    detail_markdown: str | None = None  # full report; egress may attach as a file
    response_routing: ResponseRouting
    completed_at: datetime
    trace_url: str | None = None
