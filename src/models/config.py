from pydantic import BaseModel, field_validator, ValidationInfo

class TradingConfig(BaseModel):
    trading_pair: str = "BTCUSDT"
    trade_amount_usd: float | None = 15.0
    min_bc_price: float | None = None
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
        v = float(v)
        if v < 12.0:
            return 12.0
        return v

    @field_validator("min_bc_price", mode="before")
    @classmethod
    def coerce_bc_price(cls, v: float | None) -> float | None:
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

    trailing_stop_pct: float | None = None
    price_bounce_ticks: int | None = None
    bear_trend_candles: int | None = None
    bear_trend_pct: float | None = None

    # RSI Ultra parameters
    rsi_ultra_period: int = 14
    rsi_ultra_signal_period: int = 9
    rsi_ultra_zone_mid: float = 50.0

    # Strategy / Filter mode fields
    active_modes: list[str] = ["RSI"]  # e.g. ["RSI"] or ["BC"]
    active_filters: list[str] = []     # e.g. ["BB", "BOUNCE", "BEAR"]
    bc_buy_price: float | None = None
    bc_sell_price: float | None = None
    bb_period: int | None = None

    # Agent language preference
    agent_language: str = "EN"  # EN, FR, or AR

    # Agent theme preference
    agent_theme: str = "technical"  # technical, simple, or detailed

    @field_validator("take_profit_pct")
    @classmethod
    def validate_take_profit(cls, v: float | None) -> float | None:
        if v is None or v == 0:
            return v  # 0 or None means disabled
        if not 0.1 <= v <= 100.0:
            raise ValueError("take_profit_pct must be 0 (disabled) or between 0.1 and 100.0")
        return v

    @field_validator("trailing_stop_pct")
    @classmethod
    def validate_trailing_stop(cls, v: float | None) -> float | None:
        if v is None:
            return v
        if not 0.1 <= v <= 50.0:
            raise ValueError("trailing_stop_pct must be between 0.1 and 50.0")
        return v

    @field_validator("price_bounce_ticks")
    @classmethod
    def validate_bounce_ticks(cls, v: int | None) -> int | None:
        if v is None:
            return v
        if not 1 <= v <= 20:
            raise ValueError("price_bounce_ticks must be between 1 and 20")
        return v

    @field_validator("bear_trend_candles")
    @classmethod
    def validate_bear_candles(cls, v: int | None) -> int | None:
        if v is None:
            return v
        if not 3 <= v <= 500:
            raise ValueError("bear_trend_candles must be between 3 and 500")
        return v

    @field_validator("bear_trend_pct")
    @classmethod
    def validate_bear_pct(cls, v: float | None) -> float | None:
        if v is None:
            return v
        if not 0.1 <= v <= 20.0:
            raise ValueError("bear_trend_pct must be between 0.1 and 20.0")
        return v

    @field_validator("rsi_ultra_period", "rsi_ultra_signal_period")
    @classmethod
    def validate_ultra_periods(cls, v: int) -> int:
        if not 1 <= v <= 500:
            raise ValueError("RSI Ultra periods must be between 1 and 500")
        return v

    @field_validator("rsi_ultra_zone_mid")
    @classmethod
    def validate_ultra_zone(cls, v: float) -> float:
        if not 1.0 <= v <= 99.0:
            raise ValueError("rsi_ultra_zone_mid must be between 1 and 99")
        return v

    @field_validator("agent_language")
    @classmethod
    def validate_language(cls, v: str) -> str:
        v = v.upper()
        if v not in ["EN", "FR", "AR"]:
            raise ValueError("agent_language must be EN, FR, or AR")
        return v

    @field_validator("agent_theme")
    @classmethod
    def validate_theme(cls, v: str) -> str:
        v = v.lower()
        if v not in ["technical", "simple", "detailed"]:
            raise ValueError("agent_theme must be technical, simple, or detailed")
        return v
