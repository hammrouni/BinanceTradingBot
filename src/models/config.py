from pydantic import BaseModel, field_validator, ValidationInfo

class TradingConfig(BaseModel):
    trading_pair: str = "BTCUSDT"
    trade_amount_usd: float | None = 15.0
    rsi_oversold: int | None = 30
    rsi_overbought: int | None = 70
    stop_loss_pct: float | None = 5.0
    take_profit_pct: float | None = 2.0

    @field_validator("trading_pair")
    @classmethod
    def validate_pair(cls, v: str) -> str:
        # Strip whitespace and force uppercase (e.g. " btcusdt " -> "BTCUSDT")
        v = v.strip().upper()
        if not v:
            raise ValueError("trading_pair cannot be empty")
        return v

    @field_validator("rsi_oversold", "rsi_overbought")
    @classmethod
    def validate_rsi(cls, v: int | None) -> int | None:
        if v is None:
            return v
        if not 1 <= v <= 100:
            raise ValueError("rsi thresholds must be between 1 and 100")
        return v

    @field_validator("trade_amount_usd", mode="before")
    @classmethod
    def coerce_amount(cls, v: float | None, info: ValidationInfo) -> float | None:
        if v is None:
            return None
        return float(v)

    @field_validator("stop_loss_pct")
    @classmethod
    def validate_stop_loss(cls, v: float | None) -> float | None:
        if v is None:
            return v
        if not 0.1 <= v <= 50.0:
            raise ValueError("stop_loss_pct must be between 0.1 and 50.0")
        return v

    @field_validator("take_profit_pct")
    @classmethod
    def validate_take_profit(cls, v: float | None) -> float | None:
        if v is None or v == 0:
            return v  # 0 or None means disabled
        if not 0.1 <= v <= 100.0:
            raise ValueError("take_profit_pct must be 0 (disabled) or between 0.1 and 100.0")
        return v
