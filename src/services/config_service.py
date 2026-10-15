"""Single code path for changing the trading config (PUT /config and the MCP/chat tools)."""
from fastapi import HTTPException

from src.core.config_manager import load_config, save_config
from src.models.config import TradingConfig
from src.services.rsi_history_service import add_rsi_threshold


async def apply_config_update(new_config: TradingConfig, app) -> TradingConfig:
    """Persist `new_config` and apply it to the running app.

    Raises HTTPException 409 (pair change with an open position) or 502 (market feed switch failed).
    """
    old_config = load_config()
    bot = getattr(app.state, "bot_engine", None)
    runtime = getattr(app.state, "market_runtime", None)

    pair_changed = new_config.trading_pair != old_config.trading_pair
    if pair_changed and bot is not None and bot.open_position is not None:
        raise HTTPException(
            status_code=409,
            detail=(f"Cannot change the trading pair from {old_config.trading_pair} to "
                    f"{new_config.trading_pair} while a position is open. Close the position first."),
        )
    if pair_changed and runtime is not None:
        # Fetch + reseed first: if Binance is unreachable the old pair and config stay in place
        try:
            await runtime.change_pair(new_config)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Could not switch the market feed to {new_config.trading_pair}: {e}")

    if new_config.rsi_oversold != old_config.rsi_oversold:
        add_rsi_threshold("oversold", new_config.rsi_oversold)
    if new_config.rsi_overbought != old_config.rsi_overbought:
        add_rsi_threshold("overbought", new_config.rsi_overbought)

    save_config(new_config)
    app.state.config = new_config

    if runtime is not None and not pair_changed:
        runtime.reconfigure_ultra(new_config)
    if bot:
        await bot.refresh_thresholds(new_config)
    return new_config


async def update_config_field(field: str, value, app) -> dict:
    """Validate and apply a single-field change. Returns {"success", "updated"} or {"error"}."""
    allowed = set(TradingConfig.model_fields.keys())
    if field not in allowed:
        return {"error": f"Unknown config field '{field}'. Allowed: {sorted(allowed)}"}
    try:
        data = load_config().model_dump()
        data[field] = value
        new_config = TradingConfig(**data)
        await apply_config_update(new_config, app)
        return {"success": True, "updated": {field: getattr(new_config, field)}}
    except HTTPException as e:
        return {"error": e.detail}
    except Exception as e:
        return {"error": str(e)}
