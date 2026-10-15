"""Optional (None) config fields: model validation and engine behaviour."""
from src.models.config import TradingConfig

from .conftest import open_position


def test_trading_config_optional_fields():
    config = TradingConfig(
        trading_pair="BTCUSDT",
        trade_amount_usd=None,
        rsi_oversold=None,
        rsi_overbought=None,
        stop_loss_pct=None,
        take_profit_pct=None,
    )
    assert config.trade_amount_usd is None
    assert config.rsi_oversold is None
    assert config.rsi_overbought is None
    assert config.stop_loss_pct is None
    assert config.take_profit_pct is None


def test_trading_config_validators_with_none():
    assert TradingConfig(rsi_oversold=None).rsi_oversold is None
    assert TradingConfig(stop_loss_pct=None).stop_loss_pct is None
    assert TradingConfig(take_profit_pct=None).take_profit_pct is None


async def test_bot_engine_skips_buy_without_amount(engine, fake_client):
    await engine.start()
    config = TradingConfig(trade_amount_usd=None, rsi_oversold=30)
    await engine.process_market_update(rsi=25.0, price=50000.0, config=config)
    fake_client.execute_market_buy.assert_not_called()


async def test_bot_engine_skips_buy_without_rsi_oversold(engine, fake_client):
    await engine.start()
    config = TradingConfig(trade_amount_usd=15.0, rsi_oversold=None)
    await engine.process_market_update(rsi=10.0, price=50000.0, config=config)
    fake_client.execute_market_buy.assert_not_called()


async def test_bot_engine_skips_sl_tp_when_none(engine, fake_client):
    await engine.start()
    config = TradingConfig(stop_loss_pct=None, take_profit_pct=None, rsi_overbought=None)
    open_position(engine, config, price=100.0)
    assert engine._stop_loss_price is None and engine._take_profit_price is None

    await engine.process_market_update(rsi=50.0, price=50.0, config=config)    # big drop
    await engine.process_market_update(rsi=50.0, price=200.0, config=config)   # big rise
    await engine.on_price_tick(10.0, config)
    await engine.on_price_tick(1000.0, config)

    fake_client.execute_market_sell.assert_not_called()
    assert engine.open_position is not None
