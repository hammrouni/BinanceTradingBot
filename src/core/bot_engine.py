"""bot_engine.py — Core entry point for the trading bot.

Refactored to be a thin orchestrator that delegates logic to:
- Strategies: RSI, BC, etc.
- Executor: Buy/Sell technicals
- PositionManager: Persistence/Reconciliation
"""

import asyncio
import json
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from src.models.config import TradingConfig
from src.utils.logger import get_logger
from src.core.strategies.base import TickContext, Signal
from src.core.strategies.rsi import RSIStrategy
from src.core.strategies.bc import BCStrategy
from src.core.executor import TradeExecutor
from src.core.position_manager import PositionManager

logger = get_logger(__name__)

_STATE_FILE = Path("data/bot_state.json")


class BotState(str, Enum):
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    ERROR = "ERROR"


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

    def __init__(self, broadcaster=None) -> None:
        self.state: BotState = BotState.STOPPED
        self.started_at: datetime | None = None
        self.open_position: OrderResult | None = None
        self._stop_loss_price: float | None = None
        self._take_profit_price: float | None = None
        
        # ConnectionManager injected at construction
        self._broadcaster = broadcaster  
        self._buy_lock: asyncio.Lock = asyncio.Lock()
        
        # Cache for UI/Broadcasting
        self.balances: dict = {
            "prod": {"assets": {}, "total_net_worth": 0.0},
            "trading": {"assets": {}, "total_net_worth": 0.0},
            "trading_env": "testnet"
        }
        self.market_history: deque[dict] = deque(maxlen=1000)

        # Components
        self._executor = None # Will be set by set_binance_client
        self._pos_manager = None
        
        # Strategies
        self._strategies = {
            "RSI": RSIStrategy(),
            "BC": BCStrategy(),
        }
        
        self._restore_state()

    def set_binance_client(self, binance_client):
        """Inject binance_client and initialize dependent components."""
        self._executor = TradeExecutor(binance_client, self._broadcaster)
        self._pos_manager = PositionManager(binance_client, self._broadcaster)

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
                "open_position": {
                    "order_id": pos.order_id,
                    "pair": pos.pair,
                    "quantity": pos.quantity,
                    "price": pos.price,
                    "executed_at": pos.executed_at.isoformat(),
                } if pos else None,
            }
            _STATE_FILE.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.warning("Could not persist bot state: %s", e, exc_info=True)

    # ── Lifecycle ────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self.state not in (BotState.STOPPED, BotState.ERROR):
            raise InvalidStateTransitionError(f"Cannot start from {self.state}")
        self.state = BotState.RUNNING
        self.started_at = datetime.now(timezone.utc)
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
        for s in self._strategies.values():
            s.on_reset()

    async def set_error(self, message: str) -> None:
        self.state = BotState.ERROR
        self._persist_state()
        logger.error("Bot error: %s", message)
        await self._broadcast_state()

    # ── Manual Controls ──────────────────────────────────────────────────────────

    async def manual_buy(self, config: TradingConfig) -> None:
        if self.open_position is not None:
            raise InvalidStateTransitionError("Cannot manual buy: Position already open")
        if self._buy_lock.locked():
            raise InvalidStateTransitionError("Buy already in progress")

        logger.info("Manual BUY triggered")
        
        # In BC mode (no trade_amount_usd), use available USDT balance
        amount_override = None
        if config.trade_amount_usd is None:
            amount_override = self._get_available_usdt()
            if amount_override < 1.0:
                raise InvalidStateTransitionError(f"Cannot manual buy: Insufficient USDT (${amount_override:.2f})")
        
        amount_usd = amount_override if amount_override is not None else config.trade_amount_usd
        async with self._buy_lock:
            result = await self._executor.execute_buy(config.trading_pair, amount_usd, reason="manual")
            if result:
                self.open_position = result
                self._update_thresholds_after_buy(result, config)
                self._persist_state()
                await self.update_balances(config.trading_pair)

    async def manual_sell(self, config: TradingConfig) -> None:
        if self.open_position is None:
            raise InvalidStateTransitionError("Cannot manual sell: No open position")
        
        logger.info("Manual SELL triggered")
        result = await self._executor.execute_sell(
            self.open_position.pair, 
            self.open_position.quantity, 
            self.open_position.price,
            reason="manual"
        )
        if result:
            self._clear_position()
            self._persist_state()
            await self.update_balances(config.trading_pair)

    # ── Market Processing ────────────────────────────────────────────────────────

    async def process_market_update(
        self,
        rsi: float | None,
        price: float,
        config: TradingConfig,
    ) -> None:
        """Evaluate market update and check if any trade should be executed."""
        # 1. Update internal state
        self._record_market_data(price, rsi)
        self._update_trailing_stop(price, config)
        
        # 2. Check risk management (SL / TP)
        # These work even when paused
        if self.state in (BotState.RUNNING, BotState.PAUSED) and self.open_position is not None:
            if self._check_stop_loss(price):
                await self._execute_sell_orchestration(price, config, "stop_loss")
                return
            
            if self._check_take_profit(price, config):
                await self._execute_sell_orchestration(price, config, "take_profit")
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
            buy_lock_held=self._buy_lock.locked()
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
                await self._execute_sell_orchestration(price, config, res.reason)
                break

    def _record_market_data(self, price: float, rsi: float | None) -> None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.market_history.append({
            "price": price,
            "rsi": rsi,
            "timestamp": now
        })
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

        async with self._buy_lock:
            result = await self._executor.execute_buy(config.trading_pair, amount_usd, reason=reason)
            if result:
                self.open_position = result
                self._update_thresholds_after_buy(result, config)
                self._persist_state()
                await self.update_balances(config.trading_pair)

    async def _execute_sell_orchestration(self, price, config, reason):
        if not self.open_position:
            return
            
        result = await self._executor.execute_sell(
            self.open_position.pair, 
            self.open_position.quantity, 
            self.open_position.price,
            reason=reason
        )
        if result:
            self._clear_position()
            self._persist_state()
            await self.update_balances(config.trading_pair)

    def _clear_position(self):
        self.open_position = None
        self._stop_loss_price = None
        self._take_profit_price = None
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

    def _update_thresholds_after_buy(self, result, config):
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

    async def refresh_thresholds(self, config: TradingConfig) -> None:
        """Update SL/TP prices for an open position when the config changes."""
        if not self.open_position:
            return
        self._update_thresholds_after_buy(self.open_position, config)
        self._persist_state()
        await self._broadcast_state()

    # ── Wallet & Reconciliation ──────────────────────────────────────────────────

    async def update_balances(self, symbol: str, config: TradingConfig | None = None) -> None:
        self.balances = await self._executor._binance_client.get_symbol_balances(symbol)
        if config:
            await self.sync_open_position(config)
        await self._broadcast_state()

    async def sync_open_position(self, config: TradingConfig) -> None:
        if self.open_position is None:
            recovered = await self._pos_manager.recover_open_position(config.trading_pair)
            if recovered:
                self.open_position = recovered
                self._persist_state()

        if self.open_position is not None:
            reconciled, changed = await self._pos_manager.reconcile_open_position(self.open_position, config.trading_pair)
            if reconciled is None: # Dust cleared
                self._clear_position()
                self._persist_state()
            elif changed:
                self.open_position = reconciled
                self._persist_state()
            
            if self.open_position:
                await self.refresh_thresholds(config)

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
