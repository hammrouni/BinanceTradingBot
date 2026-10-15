import uuid
from typing import Literal

from pydantic import BaseModel, Field


class TradeRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    executed_at: str  # ISO 8601 UTC
    pair: str
    direction: Literal["buy", "sell"]
    amount_usd: float
    quantity: float
    entry_price: float
    order_id: str
    is_test: bool = Field(default=False)
    fee_usd: float = Field(default=0.0)
    reason: str | None = None
    pnl_usd: float | None = None

    @classmethod
    def from_order_result(
        cls,
        result,
        direction: Literal["buy", "sell"],
        amount_usd: float,
        is_test: bool = False,
        reason: str | None = None,
    ) -> "TradeRecord":
        return cls(
            executed_at=result.executed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            pair=result.pair,
            direction=direction,
            amount_usd=amount_usd,
            quantity=result.quantity,
            entry_price=result.price,
            order_id=result.order_id,
            is_test=is_test,
            fee_usd=getattr(result, "fee_usd", 0.0),
            reason=reason,
        )
