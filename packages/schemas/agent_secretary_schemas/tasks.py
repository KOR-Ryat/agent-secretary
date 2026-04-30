from datetime import datetime

from pydantic import BaseModel

from agent_secretary_schemas.events import ResponseRouting


class TaskSpec(BaseModel):
    task_id: str
    event_id: str
    workflow: str
    workflow_input: dict
    response_routing: ResponseRouting
    created_at: datetime
    shadow: bool = False
    """Backstage tasks: trace-only, no result published.

    When True the agents service writes the trace row but skips
    `publish_result()` — the egress channel never sees this task. Used
    by the persona A/B comparator (issue #2) and other research-only
    workflows that shouldn't surface to end users.
    """
