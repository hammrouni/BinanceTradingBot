"""bot_engine.py — Core entry point for the trading bot.

Refactored to be a thin orchestrator that delegates logic to:
- Strategies: RSI, BC, etc.
- Executor: Buy/Sell technicals
- PositionManager: Persistence/Reconciliation
"""

import asyncio
import json
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from src.models.config import TradingConfig
from src.utils.fs import atomic_write_json
from src.utils.logger import get_logger
from src.core.strategies.base import TickContext, Signal
from src.core.strategies import RSIStrategy, BCStrategy, RsiUltraStrategy
from src.core.executor import TradeExecutor
from src.core.position_manager import PositionManager

logger = get_logger(__name__)

_STATE_FILE = Path("data/bot_state.json")

# Failed-sell policy: exponential backoff between automatic retries, then give up (ERROR state).
SELL_BACKOFF_BASE_SECONDS = 5.0
SELL_BACKOFF_MAX_SECONDS = 60.0
SELL_MAX_FAILURES = 5


class BotState(str, Enum):
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    ERROR = "ERROR"


# States in which an open position keeps its SL/TP protection. ERROR is excluded on purpose:
# it means "stop acting automatically, a human must look", and is reached after repeated sell failures.
_PROTECTED_STATES = (BotState.RUNNING, BotState.PAUSED, BotState.STOPPED)


class InvalidStateTransitionError(Exception):
    pass


@dataclass
class OrderResult:
    order_id: str
    pair: str
    quantity: float
    price: float
    executed_at: datetime


class BotEngine:
    """The orchestrator of the trading bot.

    Coordinates market updates, strategy evaluations and trade execution.
    """

    def __init__(self, broadcaster=None, restore_running: bool = False, clock=time.monotonic) -> None:
        """
        Args:
            restore_running: if True a persisted RUNNING state is restored as RUNNING after a restart;
                by default it comes back PAUSED so nothing trades until the user resumes.
            clock: monotonic time source (injectable for tests).
        """
        self._restore_running = restore_running
        self._clock = clock
        self.state: BotState = BotState.STOPPED
        self.started_at: datetime | None = None
        self.open_position: OrderResult | None = None
        self._stop_loss_price: float | None = None
        self._take_profit_price: float | None = None
        self._support_level: float | None = None   # support price frozen at entry (support-level SL)
        self._risk_key: tuple | None = None        # risk config the current SL/TP were computed from
        self._config: TradingConfig | None = None  # latest config, used by the per-tick risk checks

        # Failed-sell backoff
        self._sell_failures: int = 0
        self._next_sell_at: float = 0.0

        # RSI Ultra state (for crossover detection)
        self._prev_rsi_ultra_raw: float | None = None
        self._prev_rsi_ultra_signal: float | None = None

        # ConnectionManager injected at construction
        self._broadcaster = broadcaster
        # One lock for every order (manual + automatic, buy + sell) so they can never overlap
        self._trade_lock: asyncio.Lock = asyncio.Lock()

        # Cache for UI/Broadcasting
        self.balances: dict = {
            "prod": {"assets": {}, "total_net_worth": 0.0},
            "trading": {"assets": {}, "total_net_worth": 0.0},
            "trading_env": "testnet"
        }
        self.market_history: deque[dict] = deque(maxlen=1440)
        self._history_candle: dict | None = None   # accumulating 1-min OHLC

        # Components
        self._binance_client = None
        self._executor = None # Will be set by set_binance_client
        self._pos_manager = None

        # Strategies
        self._strategies = {
            "RSI": RSIStrategy(),
            "BC": BCStrategy(),
            "RSI_ULTRA": RsiUltraStrategy(),
        }

        self._restore_state()

    def set_binance_client(self, binance_client):
        """Inject binance_client and initialize dependent components."""
        self._binance_client = binance_client
        self._executor = TradeExecutor(binance_client, self._broadcaster)
        self._pos_manager = PositionManager(binance_client, self._broadcaster)

    def set_config(self, config: TradingConfig) -> None:
        """Remember the live config so per-tick risk checks use current settings."""
        self._config = config

    @property
    def is_active(self) -> bool:
        return self.state == BotState.RUNNING

    def get_uptime_seconds(self) -> int:
        """Return the number of seconds the bot has been running/active."""
        if not self.started_at:
            return 0
        now = datetime.now(timezone.utc)
        return int((now - self.started_at).total_seconds())

    # ── State Persistence ────────────────────────────────────────────────────────

    def _restore_state(self) -> None:
        """Restore persisted state from disk on startup."""
        try:
            if not _STATE_FILE.exists():
                return
            data = json.loads(_STATE_FILE.read_text())
            self.state = BotState(data.get("state", BotState.STOPPED))
            if self.state == BotState.RUNNING and not self._restore_running:
                logger.warning("Bot was RUNNING before restart: restoring as PAUSED (resume it from the dashboard)")
                self.state = BotState.PAUSED
            started_at = data.get("started_at")
            if started_at:
                self.started_at = datetime.fromisoformat(started_at)
            pos = data.get("open_position")
            if pos:
                self.open_position = OrderResult(
                    order_id=pos["order_id"],
                    pair=pos["pair"],
                    quantity=pos["quantity"],
                    price=pos["price"],
                    executed_at=datetime.fromisoformat(pos["executed_at"]),
                )
                self._stop_loss_price = data.get("stop_loss_price")
                self._take_profit_price = data.get("take_profit_price")
                self._support_level = data.get("support_level")
                risk_key = data.get("risk_key")
                self._risk_key = tuple(risk_key) if risk_key else None
            logger.info("Bot state restored from disk: %s", self.state.value)
        except Exception as e:
            logger.warning("Could not restore bot state: %s", e, exc_info=True)

    def _persist_state(self) -> None:
        """Write current state to disk so it survives restarts."""
        try:
            pos = self.open_position
            data: dict = {
                "state": self.state.value,
                "started_at": self.started_at.isoformat() if self.started_at else None,
                "stop_loss_price": self._stop_loss_price,
                "take_profit_price": self._take_profit_price,
                "support_level": self._support_level,
                "risk_key": list(self._risk_key) if self._risk_key else None,
                "open_position": {
                    "order_id": pos.order_id,
                    "pair": pos.pair,
                    "quantity": pos.quantity,
                    "price": pos.price,
                    "executed_at": pos.executed_at.isoformat(),
                } if pos else None,
            }
            atomic_write_json(_STATE_FILE, data)
        except Exception as e:
            logger.warning("Could not persist bot state: %s", e, exc_info=True)

    # ── Lifecycle ────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self.state not in (BotState.STOPPED, BotState.ERROR):
            raise InvalidStateTransitionError(f"Cannot start from {self.state}")
        self.state = BotState.RUNNING
        self.started_at = datetime.now(timezone.utc)
        self._reset_sell_backoff()
        self._reset_strategies()
        self._persist_state()
        logger.info("Bot started — state: RUNNING")
        await self._broadcast_state()

    async def pause(self) -> None:
        if self.state != BotState.RUNNING:
            raise InvalidStateTransitionError(f"Cannot pause from {self.state}")
        self.state = BotState.PAUSED
        self._persist_state()
        logger.info("Bot paused — state: PAUSED")
        await self._broadcast_state()

    async def resume(self) -> None:
        if self.state != BotState.PAUSED:
            raise InvalidStateTransitionError(f"Cannot resume from {self.state}")
        self.state = BotState.RUNNING
        self._reset_strategies()
        self._persist_state()
        logger.info("Bot resumed — state: RUNNING")
        await self._broadcast_state()

    async def stop(self) -> None:
        if self.state not in (BotState.RUNNING, BotState.PAUSED):
            raise InvalidStateTransitionError(f"Cannot stop from {self.state}")
        self.state = BotState.STOPPED
        self.started_at = None
        self._reset_strategies()
        self._persist_state()
        logger.info("Bot stopped — state: STOPPED")
        await self._broadcast_state()

    def _reset_strategies(self) -> None:
        self._prev_rsi_ultra_raw = None
        self._prev_rsi_ultra_signal = None
        for s in self._strategies.values():
            s.on_reset()

    async def set_error(self, message: str) -> None:
        self.state = BotState.ERROR
        self._persist_state()
        logger.error("Bot error: %s", message)
        await self._broadcast_state()
        if self._broadcaster:
            await self._broadcaster.broadcast({
                "type": "error",
                "payload": {"code": "API_FAILURE", "message": message},
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            })

    def _reset_sell_backoff(self) -> None:
        self._sell_failures = 0
        self._next_sell_at = 0.0

    # ── Manual Controls ──────────────────────────────────────────────────────────

    async def manual_buy(self, config: TradingConfig) -> None:
        if self.open_position is not None:
            raise InvalidStateTransitionError("Cannot manual buy: Position already open")
        if self._trade_lock.locked():
            raise InvalidStateTransitionError("Another trade is already in progress")

        logger.info("Manual BUY triggered")

        # In BC mode (no trade_amount_usd), use available USDT balance
        amount_usd = config.trade_amount_usd
        if amount_usd is None:
            amount_usd = self._get_available_usdt()
            if amount_usd < 1.0:
                raise InvalidStateTransitionError(f"Cannot manual buy: Insufficient USDT (${amount_usd:.2f})")

        await self._buy(config, amount_usd, "manual")

    async def manual_sell(self, config: TradingConfig) -> None:
        if self.open_position is None:
            raise InvalidStateTransitionError("Cannot manual sell: No open position")
        if self._trade_lock.locked():
            raise InvalidStateTransitionError("Another trade is already in progress")

        logger.info("Manual SELL triggered")
        await self._sell(config, "manual", manual=True)

    # ── Market Processing ────────────────────────────────────────────────────────

    async def process_market_update(
        self,
        rsi: float | None,
        price: float,
        config: TradingConfig,
        open: float | None = None,
        high: float | None = None,
        low: float | None = None,
        rsi_ultra_raw: float | None = None,
        rsi_ultra_signal: float | None = None,
    ) -> None:
        """Evaluate market update and check if any trade should be executed."""
        # 1. Update internal state
        self._record_market_data(
            price, rsi,
            open=open, high=high, low=low,
            rsi_ultra_raw=rsi_ultra_raw,
            rsi_ultra_signal=rsi_ultra_signal
        )
        self._config = config

        # 2. Check risk management (SL / TP): also done on every live tick by on_price_tick()
        if await self._run_risk_checks(price, config):
            return

        # 3. Check strategies (only when RUNNING)
        if not self.is_active:
            return

        active_modes = getattr(config, 'active_modes', None) or ['RSI']
        ctx = TickContext(
            price=price,
            rsi=rsi,
            config=config,
            has_open_position=self.open_position is not None,
            buy_lock_held=self._trade_lock.locked(),
            rsi_ultra_raw=rsi_ultra_raw,
            rsi_ultra_signal=rsi_ultra_signal,
            prev_rsi_ultra_raw=self._prev_rsi_ultra_raw,
            prev_rsi_ultra_signal=self._prev_rsi_ultra_signal,
        )

        for mode_name in active_modes:
            strategy = self._strategies.get(mode_name)
            if not strategy:
                continue

            res = strategy.on_tick(ctx)
            if res.signal == Signal.BUY and not self.open_position:
                await self._execute_buy_orchestration(price, config, res.reason, res.amount_override)
                break
            elif res.signal == Signal.SELL and self.open_position:
                await self._sell(config, res.reason)
                break

        # 4. Advance rolling state for next tick
        self._prev_rsi_ultra_raw = rsi_ultra_raw
        self._prev_rsi_ultra_signal = rsi_ultra_signal

    async def on_price_tick(self, price: float, config: TradingConfig | None = None) -> None:
        """Lightweight per-tick hook: SL/TP/trailing only, never strategies or market history.

        Fed with every live price from the data stream, so stops fire mid-candle.
        """
        config = config or self._config
        if config is None:
            return
        await self._run_risk_checks(price, config)

    async def _run_risk_checks(self, price: float, config: TradingConfig) -> bool:
        """Trailing update, then SL, then TP. Returns True if a sell was triggered."""
        if self.open_position is None or self.state not in _PROTECTED_STATES:
            return False
        self._update_trailing_stop(price, config)
        if self._check_stop_loss(price):
            await self._sell(config, "stop_loss")
            return True
        if self._check_take_profit(price, config):
            await self._sell(config, "take_profit")
            return True
        return False

    def _record_market_data(
        self,
        price: float,
        rsi: float | None,
        open: float | None = None,
        high: float | None = None,
        low: float | None = None,
        rsi_ultra_raw: float | None = None,
        rsi_ultra_signal: float | None = None,
    ) -> None:
        """Accumulate per-tick data into 1-minute OHLC candles before appending to history."""
        from math import floor
        now = datetime.now(timezone.utc)
        minute_ts = floor(now.timestamp() / 60) * 60  # seconds aligned to minute
        ts_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        o = open  if open  is not None else price
        h = high  if high  is not None else price
        l = low   if low   is not None else price

        if self._history_candle is None or self._history_candle["_minute"] != minute_ts:
            # New minute: flush the previous candle (if any) then start a new one
            if self._history_candle is not None:
                # Flush: remove internal _minute key before storing
                stored = {k: v for k, v in self._history_candle.items() if k != "_minute"}
                self.market_history.append(stored)
            # Start fresh candle for this minute
            self._history_candle = {
                "_minute":   minute_ts,
                "timestamp": ts_str,
                "price":     price,   # close (updated each tick)
                "open":      o,
                "high":      h,
                "low":       l,
                "rsi":       rsi,
                "rsi_ultra_raw": rsi_ultra_raw,
                "rsi_ultra_signal": rsi_ultra_signal,
            }
        else:
            # Same minute: update running OHLC
            self._history_candle["price"] = price          # close = latest
            self._history_candle["high"]  = max(self._history_candle["high"], h)
            self._history_candle["low"]   = min(self._history_candle["low"],  l)
            if rsi is not None:
                self._history_candle["rsi"] = rsi          # keep latest RSI
            if rsi_ultra_raw is not None:
                self._history_candle["rsi_ultra_raw"] = rsi_ultra_raw
            if rsi_ultra_signal is not None:
                self._history_candle["rsi_ultra_signal"] = rsi_ultra_signal

        # Keep strategy history in sync
        for s in self._strategies.values():
            if hasattr(s, 'record_price'):
                s.record_price(price)

    # ── Orchestration Helpers ────────────────────────────────────────────────────

    async def _execute_buy_orchestration(self, price, config, reason, amount_override=None):
        amount_usd = amount_override if amount_override is not None else config.trade_amount_usd
        if not amount_usd or amount_usd <= 0:
            logger.error("Cannot execute buy: no valid amount")
            return

        if (
            config.min_move_pct is not None
            and (config.take_profit_pct is None or config.take_profit_pct < config.min_move_pct)
        ):
            logger.info(
                "Buy skipped: take_profit_pct %.2f%% < min_move_pct %.2f%%",
                config.take_profit_pct or 0,
                config.min_move_pct,
            )
            return

        if self._trade_lock.locked():
            return
        await self._buy(config, amount_usd, reason)

    async def _buy(self, config: TradingConfig, amount_usd: float, reason: str) -> None:
        async with self._trade_lock:
            if self.open_position is not None:
                return
            result = await self._executor.execute_buy(config.trading_pair, amount_usd, reason=reason)
            if not result:
                return
            self.open_position = result  # quantity = what this buy filled, never the wallet total
            self._reset_sell_backoff()
            self._update_thresholds_after_buy(result, config)
            self._persist_state()
        await self._refresh_after_trade(config)

    async def _sell(self, config: TradingConfig, reason: str, manual: bool = False) -> bool:
        """Sell the bot-owned position under the shared trade lock. Returns True when sold."""
        if self.open_position is None:
            return False
        # Automatic sells honour the backoff; an explicit manual sell always gets a try.
        if not manual and self._clock() < self._next_sell_at:
            return False
        if self._trade_lock.locked():
            return False

        async with self._trade_lock:
            pos = self.open_position
            if pos is None:  # sold by someone else while we waited
                return False
            result = await self._executor.execute_sell(pos.pair, pos.quantity, pos.price, reason=reason)
            if result:
                self._reset_sell_backoff()
                self._clear_position()
                self._persist_state()
            else:
                await self._on_sell_failed(config)
        if result:
            await self._refresh_after_trade(config)
        return bool(result)

    async def _on_sell_failed(self, config: TradingConfig) -> None:
        self._sell_failures += 1
        delay = min(SELL_BACKOFF_BASE_SECONDS * 2 ** (self._sell_failures - 1), SELL_BACKOFF_MAX_SECONDS)
        self._next_sell_at = self._clock() + delay
        last_error = getattr(self._executor, "last_error", None) or "unknown error"
        logger.warning("Sell failed (%d/%d): %s. Next attempt in %.0fs",
                       self._sell_failures, SELL_MAX_FAILURES, last_error, delay)

        # A wallet mismatch or dust rejection means our quantity is stale: re-sync it.
        lowered = str(last_error).lower()
        if "insufficient" in lowered or "unsellable_dust" in lowered:
            try:
                await self.sync_open_position(config)
            except Exception as e:
                logger.warning("Re-sync after rejected sell failed: %s", e)

        if self._sell_failures >= SELL_MAX_FAILURES and self.state != BotState.ERROR:
            await self.set_error(
                f"Sell failed {self._sell_failures} times in a row ({last_error}); "
                "automatic trading stopped. Position is still open."
            )

    async def _refresh_after_trade(self, config: TradingConfig) -> None:
        try:
            await self.update_balances(config.trading_pair)
        except Exception as e:
            logger.warning("Wallet refresh after trade failed: %s", e)

    def _clear_position(self):
        self.open_position = None
        self._stop_loss_price = None
        self._take_profit_price = None
        self._support_level = None
        self._risk_key = None
        self._reset_strategies()

    # ── Risk Management ──────────────────────────────────────────────────────────

    def _update_trailing_stop(self, price, config):
        if (
            self.open_position is not None
            and config.trailing_stop_pct is not None
            and self._stop_loss_price is not None
        ):
            new_trailing = price * (1 - config.trailing_stop_pct / 100)
            if new_trailing > self._stop_loss_price:
                logger.info("Trailing stop ratcheted: %.2f → %.2f", self._stop_loss_price, new_trailing)
                self._stop_loss_price = new_trailing
                self._persist_state()

    def _check_stop_loss(self, price) -> bool:
        return self._stop_loss_price is not None and price < self._stop_loss_price

    def _check_take_profit(self, price, config) -> bool:
        # In BC mode, TP is anchored to BC price
        bc_mode_tp = (
            config.min_bc_price is not None
            and config.take_profit_pct is not None
            and config.take_profit_pct > 0
        )
        effective_tp = (
            config.min_bc_price * (1 + config.take_profit_pct / 100)
            if bc_mode_tp
            else self._take_profit_price
        )

        # Sync stored value if corrected
        if bc_mode_tp and effective_tp != self._take_profit_price:
            self._take_profit_price = effective_tp
            self._persist_state()

        return effective_tp is not None and price >= effective_tp

    @staticmethod
    def _risk_config_key(config: TradingConfig) -> tuple:
        """The config fields SL/TP are derived from."""
        return (
            config.stop_loss_pct, config.trailing_stop_pct, config.take_profit_pct,
            config.sl_lookback_candles, config.sl_buffer_pct, config.min_bc_price,
        )

    def _update_thresholds_after_buy(self, result, config, fresh_entry: bool = True):
        """Compute SL/TP for `result`. A fresh entry also freezes the support level."""
        if config.sl_lookback_candles is not None and (self.market_history or self._support_level is not None):
            if fresh_entry or self._support_level is None:
                candles = list(self.market_history)[-config.sl_lookback_candles:]
                lows = [c["low"] for c in candles if "low" in c]
                self._support_level = min(lows) if lows else None
            if self._support_level is not None:
                buffer = config.sl_buffer_pct / 100
                self._stop_loss_price = self._support_level * (1 - buffer)
                logger.info(
                    "Support-level SL: support=%.2f buffer=%.2f%% → SL=%.2f",
                    self._support_level, config.sl_buffer_pct, self._stop_loss_price,
                )
            else:
                self._stop_loss_price = None
        else:
            self._support_level = None
            if config.stop_loss_pct is not None:
                self._stop_loss_price = result.price * (1 - config.stop_loss_pct / 100)
            elif config.trailing_stop_pct is not None:
                self._stop_loss_price = result.price * (1 - config.trailing_stop_pct / 100)
            else:
                self._stop_loss_price = None

        if config.take_profit_pct is not None and config.take_profit_pct > 0:
            bc_mode = config.min_bc_price is not None
            tp_base = config.min_bc_price if bc_mode else result.price
            self._take_profit_price = tp_base * (1 + config.take_profit_pct / 100)
        else:
            self._take_profit_price = None

        self._risk_key = self._risk_config_key(config)

    async def refresh_thresholds(self, config: TradingConfig) -> None:
        """Re-derive SL/TP for an open position, only when the risk-related config changed.

        Never called from wallet syncs. Trailing progress is kept: with a trailing stop
        the SL can only move up.
        """
        self._config = config
        if not self.open_position:
            return
        if self._risk_key == self._risk_config_key(config):
            return
        previous_sl = self._stop_loss_price
        self._update_thresholds_after_buy(self.open_position, config, fresh_entry=False)
        if (
            config.trailing_stop_pct is not None
            and previous_sl is not None
            and (self._stop_loss_price is None or self._stop_loss_price < previous_sl)
        ):
            self._stop_loss_price = previous_sl
        self._persist_state()
        await self._broadcast_state()

    # ── Wallet & Reconciliation ──────────────────────────────────────────────────

    async def update_balances(self, symbol: str, config: TradingConfig | None = None) -> None:
        self.balances = await self._binance_client.get_symbol_balances(symbol)
        if config:
            await self.sync_open_position(config)
        await self._broadcast_state()

    async def sync_open_position(self, config: TradingConfig) -> None:
        """Recover/reconcile the bot-owned position against the wallet.

        Any failure to read the wallet leaves the position (and its SL/TP) untouched.
        Never touches SL/TP of an existing position: see refresh_thresholds().
        """
        if self.open_position is None:
            recovered = await self._pos_manager.recover_open_position(config.trading_pair)
            if recovered:
                self.open_position = recovered
                self._update_thresholds_after_buy(recovered, config)
                self._persist_state()

        if self.open_position is not None:
            try:
                reconciled, changed = await self._pos_manager.reconcile_open_position(
                    self.open_position, config.trading_pair)
            except Exception as e:
                logger.warning("Could not reconcile open position, keeping it as is: %s", e)
                return
            if reconciled is None:  # confirmed empty or dust
                self._clear_position()
                self._persist_state()
            elif changed:
                self.open_position = reconciled
                self._persist_state()

    def _get_available_usdt(self) -> float:
        try:
            assets = self.balances.get("trading", {}).get("assets", {})
            return float(assets.get("USDT (Spot)", {}).get("free", 0))
        except Exception:
            return 0.0

    # ── Communication ────────────────────────────────────────────────────────────

    async def _broadcast_state(self) -> None:
        if self._broadcaster:
            await self._broadcaster.broadcast({
                "type": "bot_status",
                "payload": {
                    "state": self.state.value,
                    "open_position": {
                        "pair": self.open_position.pair,
                        "quantity": self.open_position.quantity,
                        "entry_price": self.open_position.price,
                        "stop_loss_price": self._stop_loss_price,
                        "take_profit_price": self._take_profit_price,
                    } if self.open_position else None,
                    "balances": self.balances,
                },
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            })
