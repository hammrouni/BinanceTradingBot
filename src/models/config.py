from pydantic import BaseModel, field_validator


class TradingConfig(BaseModel):
    trading_pair: str = "BTCUSDT"
    trade_amount_usd: float = 5.0
    rsi_threshold: int = 30
    stop_loss_pct: float = 5.0

    @field_validator("rsi_threshold")
    @classmethod
    def validate_rsi(cls, v: int) -> int:
        if not 1 <= v <= 100:
            raise ValueError("rsi_threshold must be between 1 and 100")
        return v

    @field_validator("trade_amount_usd")
    @classmethod
    def validate_amount(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("trade_amount_usd must be > 0")
        return v

    @field_validator("stop_loss_pct")
    @classmethod
    def validate_stop_loss(cls, v: float) -> float:
        if not 0.1 <= v <= 50.0:
            raise ValueError("stop_loss_pct must be between 0.1 and 50.0")
        return v
