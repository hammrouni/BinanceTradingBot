from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field
import uuid

class RsiThresholdHistoryEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    type: Literal["oversold", "overbought"]
    value: int

    @classmethod
    def from_now(cls, type: Literal["oversold", "overbought"], value: int):
        return cls(type=type, value=value)
