from pydantic import BaseModel, field_validator, ValidationInfo

class TradingConfig(BaseModel):
    trading_pair: str = "BTCUSDT"
    trade_amount_usd: float = 15.0
    rsi_oversold: int = 30
    rsi_overbought: int = 70
    stop_loss_pct: float = 5.0

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
    def validate_rsi(cls, v: int) -> int:
        if not 1 <= v <= 100:
            raise ValueError("rsi thresholds must be between 1 and 100")
        return v

    @field_validator("trade_amount_usd", mode="before")
    @classmethod
    def coerce_amount(cls, v: float, info: ValidationInfo) -> float:
        val = float(v)
        # Enforce minimum 12.0 silently to fix existing configs that are too low.
        return max(val, 12.0)

    @field_validator("stop_loss_pct")
    @classmethod
    def validate_stop_loss(cls, v: float) -> float:
        if not 0.1 <= v <= 50.0:
            raise ValueError("stop_loss_pct must be between 0.1 and 50.0")
        return v
