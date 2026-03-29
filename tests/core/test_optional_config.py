import pytest
from src.models.config import TradingConfig
import src.core.bot_engine as bot_engine_module
from src.core.bot_engine import BotEngine, BotState
from unittest.mock import AsyncMock, MagicMock

@pytest.fixture(autouse=True)
def no_state_file(tmp_path):
    """Redirect state file to a temp path so tests start clean."""
    original = bot_engine_module._STATE_FILE
    bot_engine_module._STATE_FILE = tmp_path / "bot_state.json"
    yield
    bot_engine_module._STATE_FILE = original

def test_trading_config_optional_fields():
    # Test valid None values
    config = TradingConfig(
        trading_pair="BTCUSDT",
        trade_amount_usd=None,
        rsi_oversold=None,
        rsi_overbought=None,
        stop_loss_pct=None,
        take_profit_pct=None
    )
    assert config.trade_amount_usd is None
    assert config.rsi_oversold is None
    assert config.rsi_overbought is None
    assert config.stop_loss_pct is None
    assert config.take_profit_pct is None

def test_trading_config_validators_with_none():
    # Should not raise ValueError for None
    config = TradingConfig(rsi_oversold=None)
    assert config.rsi_oversold is None
    
    config = TradingConfig(stop_loss_pct=None)
    assert config.stop_loss_pct is None
    
    config = TradingConfig(take_profit_pct=None)
    assert config.take_profit_pct is None

@pytest.mark.asyncio
async def test_bot_engine_skips_buy_without_amount():
    bot = BotEngine()
    bot.state = BotState.RUNNING
    config = TradingConfig(trade_amount_usd=None, rsi_oversold=30)
    
    binance_client = AsyncMock()
    # RSI is oversold
    await bot.process_market_update(rsi=25.0, price=50000.0, binance_client=binance_client, config=config)
    
    # execute_market_buy should NOT be called
    binance_client.execute_market_buy.assert_not_called()

@pytest.mark.asyncio
async def test_bot_engine_skips_buy_without_rsi_oversold():
    bot = BotEngine()
    bot.state = BotState.RUNNING
    config = TradingConfig(trade_amount_usd=15.0, rsi_oversold=None)
    
    binance_client = AsyncMock()
    # RSI is low, but no threshold set
    await bot.process_market_update(rsi=10.0, price=50000.0, binance_client=binance_client, config=config)
    
    binance_client.execute_market_buy.assert_not_called()

@pytest.mark.asyncio
async def test_bot_engine_skips_sl_tp_when_none():
    bot = BotEngine()
    # Setup open position
    bot.open_position = MagicMock()
    bot.open_position.price = 100.0
    bot._stop_loss_price = None
    bot._take_profit_price = None
    
    config = TradingConfig(stop_loss_pct=None, take_profit_pct=None)
    binance_client = AsyncMock()
    
    # Price drops significantly
    await bot.process_market_update(rsi=50.0, price=50.0, binance_client=binance_client, config=config)
    
    # execute_market_sell should NOT be called for SL
    binance_client.execute_market_sell.assert_not_called()
    
    # Price rises significantly
    await bot.process_market_update(rsi=50.0, price=200.0, binance_client=binance_client, config=config)
    
    # execute_market_sell should NOT be called for TP
    binance_client.execute_market_sell.assert_not_called()
