from datetime import datetime

from pydantic import BaseModel, Field


class ChannelTarget(BaseModel):
    channel: str
    target: dict


class ResponseRouting(BaseModel):
    primary: ChannelTarget
    additional: list[ChannelTarget] = Field(default_factory=list)


class RawEvent(BaseModel):
    event_id: str
    source_channel: str
    received_at: datetime
    raw_payload: dict
    normalized: dict
    response_routing: ResponseRouting
