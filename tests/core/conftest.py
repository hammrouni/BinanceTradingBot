"""Shared fixtures for engine tests: isolated state file, fake Binance client."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

import src.core.bot_engine as bot_engine_module
import src.core.executor as executor_module
from src.core.bot_engine import BotEngine, OrderResult
from src.models.config import TradingConfig


def make_config(**kw) -> TradingConfig:
    base = dict(rsi_oversold=30, rsi_overbought=70, trade_amount_usd=15.0,
                stop_loss_pct=5.0, take_profit_pct=2.0)
    return TradingConfig(**{**base, **kw})


def make_order(price=50000.0, qty=0.0001, order_id="123", pair="BTCUSDT") -> OrderResult:
    return OrderResult(order_id=order_id, pair=pair, quantity=qty, price=price,
                       executed_at=datetime.now(timezone.utc))


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Keep tests off the real data/ dir and the real trade log."""
    monkeypatch.setattr(bot_engine_module, "_STATE_FILE", tmp_path / "bot_state.json")
    monkeypatch.setattr(executor_module, "log_trade", AsyncMock())
    return tmp_path


@pytest.fixture
def fake_client():
    client = MagicMock()
    client._settings.trading_env = "testnet"
    client.execute_market_buy = AsyncMock(return_value=make_order())
    client.execute_market_sell = AsyncMock(return_value=make_order())
    client.get_base_asset_balance = AsyncMock(
        return_value={"free": 0.0001, "locked": 0.0, "total": 0.0001})
    client.get_symbol_balances = AsyncMock(return_value={
        "prod": {"assets": {}, "total_net_worth": 0.0},
        "trading": {"assets": {"USDT (Spot)": {"free": 1000.0, "locked": 0.0}},
                    "total_net_worth": 1000.0},
        "trading_env": "testnet"})
    client._get_step_size = AsyncMock(return_value=0.00001)
    return client


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def broadcaster():
    b = MagicMock()
    b.broadcast = AsyncMock()
    return b


@pytest.fixture
def engine(fake_client, broadcaster, clock):
    eng = BotEngine(broadcaster=broadcaster, clock=clock)
    eng.set_binance_client(fake_client)
    return eng


def open_position(engine: BotEngine, config: TradingConfig, price=50000.0, qty=0.0001):
    """Put the engine into a bought-at-price state with thresholds set."""
    pos = make_order(price=price, qty=qty)
    engine.open_position = pos
    engine._update_thresholds_after_buy(pos, config)
    return pos
