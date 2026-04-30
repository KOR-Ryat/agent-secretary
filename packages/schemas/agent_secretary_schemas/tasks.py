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
