import asyncio
import json
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from src.models.config import TradingConfig
from src.core.trade_logger import log_trade
from src.models.trade import TradeRecord
from src.utils.logger import get_logger

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
    def __init__(self, broadcaster=None) -> None:
        self.state: BotState = BotState.STOPPED
        self.started_at: datetime | None = None
        self.open_position: OrderResult | None = None
        self._stop_loss_price: float | None = None
        self._take_profit_price: float | None = None
        self._last_rsi_was_oversold: bool = False
        self._last_rsi_was_overbought: bool = False
        self._last_price_was_below_bc: bool = False
        self._broadcaster = broadcaster  # ConnectionManager injected at construction
        self._buy_lock: asyncio.Lock = asyncio.Lock()  # Guard against concurrent buys
        self.balances: dict = {
            "prod": {"assets": {}, "total_net_worth": 0.0},
            "trading": {"assets": {}, "total_net_worth": 0.0},
            "trading_env": "testnet"
        }
        self.market_history: deque[dict] = deque(maxlen=1000)
        self._restore_state()

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

    @property
    def is_active(self) -> bool:
        return self.state == BotState.RUNNING

    async def start(self) -> None:
        if self.state not in (BotState.STOPPED, BotState.ERROR):
            raise InvalidStateTransitionError(f"Cannot start from {self.state}")
        self.state = BotState.RUNNING
        self.started_at = datetime.now(timezone.utc)
        self._last_rsi_was_oversold = False
        self._last_price_was_below_bc = False
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
        self._last_rsi_was_oversold = False
        self._last_price_was_below_bc = False
        self._persist_state()
        logger.info("Bot resumed — state: RUNNING")
        await self._broadcast_state()

    async def stop(self) -> None:
        if self.state not in (BotState.RUNNING, BotState.PAUSED):
            raise InvalidStateTransitionError(f"Cannot stop from {self.state}")
        self.state = BotState.STOPPED
        self.started_at = None
        self._last_rsi_was_oversold = False
        self._last_rsi_was_overbought = False
        self._last_price_was_below_bc = False
        self._persist_state()
        logger.info("Bot stopped — state: STOPPED")
        await self._broadcast_state()

    async def set_error(self, message: str) -> None:
        self.state = BotState.ERROR
        self._persist_state()
        logger.error("Bot error: %s", message)
        await self._broadcast_state()
        await self._broadcast({
            "type": "error",
            "payload": {"code": "API_FAILURE", "message": message},
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })

    async def manual_buy(self, binance_client, config) -> None:
        """Manually trigger a market buy, bypassing RSI signals."""
        if self.open_position is not None:
            raise InvalidStateTransitionError("Cannot manual buy: Position already open")
        if self._buy_lock.locked():
            raise InvalidStateTransitionError("Buy already in progress")

        logger.info("Manual BUY triggered")
        price = await binance_client.get_current_price(config.trading_pair)
        # In BC mode (no trade_amount_usd), use available USDT balance
        if config.trade_amount_usd is None:
            amount = self._get_available_usdt()
            if amount < 1.0:
                raise InvalidStateTransitionError(f"Cannot manual buy: Insufficient USDT (${amount:.2f})")
            await self._execute_buy(price, binance_client, config, reason="manual", amount_override=amount)
        else:
            await self._execute_buy(price, binance_client, config, reason="manual")

    async def manual_sell(self, binance_client) -> None:
        """Manually trigger a market sell, bypassing RSI signals."""
        if self.open_position is None:
            raise InvalidStateTransitionError("Cannot manual sell: No open position")
        
        logger.info("Manual SELL triggered")
        price = await binance_client.get_current_price(self.open_position.pair)
        await self._execute_sell(price, binance_client, reason="manual")

    def get_uptime_seconds(self) -> float:
        if self.started_at is None:
            return 0.0
        return (datetime.now(timezone.utc) - self.started_at).total_seconds()

    async def refresh_thresholds(self, config: TradingConfig) -> None:
        """Update SL/TP prices for an open position when the config changes."""
        if not self.open_position:
            return

        logger.info(
            "Refreshing thresholds for open position (%s): SL=%s%%, TP=%s%%",
            self.open_position.pair,
            f"{config.stop_loss_pct:.2f}" if config.stop_loss_pct is not None else "off",
            f"{config.take_profit_pct:.2f}" if config.take_profit_pct is not None else "off",
        )
        
        # SL: always based on actual entry price
        if config.stop_loss_pct is not None:
            self._stop_loss_price = self.open_position.price * (1 - config.stop_loss_pct / 100)
        else:
            self._stop_loss_price = None

        # TP: in BC mode anchor to BC price; in RSI mode anchor to entry price
        if config.take_profit_pct is not None and config.take_profit_pct > 0:
            bc_mode = config.trade_amount_usd is None and config.min_bc_price is not None
            tp_base = config.min_bc_price if bc_mode else self.open_position.price
            self._take_profit_price = tp_base * (1 + config.take_profit_pct / 100)
        else:
            self._take_profit_price = None

        self._persist_state()
        await self._broadcast_state()

    async def process_market_update(
        self,
        rsi: float | None,
        price: float,
        binance_client,
        config,
    ) -> None:
        """Process a market update tick: check stop-loss first, then buy signal."""
        # Update history cache for the dashboard
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.market_history.append({
            "price": price,
            "rsi": rsi,
            "timestamp": now
        })
        # Optional: update balances periodically (every ~60s if we're feeling generous)
        # For now, we'll focus on updates after trades.
        # 1. Stop-loss check (protect capital) - works even when paused
        if (
            self.state in (BotState.RUNNING, BotState.PAUSED)
            and self.open_position is not None
            and self._stop_loss_price is not None
            and price < self._stop_loss_price
        ):
            await self._execute_sell(price, binance_client, reason="stop_loss")
            return

        # 1b. Take-profit check (sell if goal hit) - works even when paused
        # In BC mode, TP is always anchored to BC price — override any stale stored value
        bc_mode_tp = (
            config.trade_amount_usd is None
            and config.min_bc_price is not None
            and config.take_profit_pct is not None
            and config.take_profit_pct > 0
        )
        effective_tp = (
            config.min_bc_price * (1 + config.take_profit_pct / 100)
            if bc_mode_tp
            else self._take_profit_price
        )
        # Sync stored value if BC mode corrects it (so WebSocket broadcasts correct TP)
        if bc_mode_tp and effective_tp != self._take_profit_price:
            self._take_profit_price = effective_tp
            self._persist_state()
        if (
            self.state in (BotState.RUNNING, BotState.PAUSED)
            and self.open_position is not None
            and effective_tp is not None
            and price >= effective_tp
        ):
            await self._execute_sell(price, binance_client, reason="take_profit")
            return

        # 2. BC Price buy signal — edge-triggered, price-based (no RSI needed)
        is_below_bc = config.min_bc_price is not None and price < config.min_bc_price
        if (
            self.is_active
            and self.open_position is None
            and not self._buy_lock.locked()
            and config.trade_amount_usd is None      # BC mode: no fixed amount
            and config.min_bc_price is not None
            and is_below_bc
            and not self._last_price_was_below_bc
        ):
            logger.info("BC Price signal: price %.2f dropped below BC %.2f", price, config.min_bc_price)
            amount_usd = self._get_available_usdt()
            if amount_usd >= 1.0:
                await self._execute_buy(price, binance_client, config, reason="bc_signal", amount_override=amount_usd)
        self._last_price_was_below_bc = is_below_bc

        # 3. RSI signals — edge-triggered (only when running)
        if rsi is None:
            return

        # Determine signals, handling None thresholds
        is_oversold = False
        if config.rsi_oversold is not None:
            is_oversold = rsi < config.rsi_oversold

        is_overbought = False
        if config.rsi_overbought is not None:
            is_overbought = rsi > config.rsi_overbought

        # ─── BUY SIGNAL ───────────────────────────────────────────────────────
        if (
            self.is_active
            and self.open_position is None
            and not self._buy_lock.locked()
            and config.trade_amount_usd is not None  # Guard: Trade Amount must be set
            and config.rsi_oversold is not None     # Guard: RSI Oversold must be set
            and is_oversold
            and not self._last_rsi_was_oversold
        ):
            logger.info("RSI Oversold signal detected (%.2f < %s)", rsi, config.rsi_oversold)
            await self._execute_buy(price, binance_client, config, reason="buy_signal")

        # ─── SELL SIGNAL (RSI) ────────────────────────────────────────────────
        elif (
            self.is_active
            and self.open_position is not None
            and config.rsi_overbought is not None
            and self._take_profit_price is None
            and is_overbought
            and not self._last_rsi_was_overbought
        ):
            logger.info("RSI Overbought signal detected (%.2f > %s)", rsi, config.rsi_overbought)
            await self._execute_sell(price, binance_client, reason="signal")

        self._last_rsi_was_oversold = is_oversold
        self._last_rsi_was_overbought = is_overbought

    def _get_available_usdt(self) -> float:
        """Return free USDT from the trading wallet (used for BC mode buys)."""
        try:
            assets = self.balances.get("trading", {}).get("assets", {})
            return float(assets.get("USDT (Spot)", {}).get("free", 0))
        except Exception:
            return 0.0

    async def _execute_buy(self, price: float, binance_client, config, reason: str = "buy_signal", amount_override: float | None = None) -> None:
        from src.services.binance_client import BinanceConnectionError, BinanceOrderError
        amount_usd = amount_override if amount_override is not None else config.trade_amount_usd
        if not amount_usd or amount_usd <= 0:
            logger.error("Cannot execute buy: no valid amount (trade_amount_usd=None and no override)")
            return
        async with self._buy_lock:
            try:
                result = await binance_client.execute_market_buy(
                    config.trading_pair, amount_usd
                )
                self.open_position = result
                if config.stop_loss_pct is not None:
                    self._stop_loss_price = result.price * (1 - config.stop_loss_pct / 100)
                else:
                    self._stop_loss_price = None

                if config.take_profit_pct is not None and config.take_profit_pct > 0:
                    bc_mode = reason == "bc_signal" and config.min_bc_price is not None
                    tp_base = config.min_bc_price if bc_mode else result.price
                    self._take_profit_price = tp_base * (1 + config.take_profit_pct / 100)
                else:
                    self._take_profit_price = None
                self._persist_state()
                sl = self._stop_loss_price
                logger.info(
                    "Buy executed: %s qty=%.6f price=%.2f stop-loss=%s",
                    result.pair, result.quantity, result.price, f"{sl:.2f}" if sl else "off",
                )
                is_test = (binance_client._settings.trading_env == "testnet")
                record = TradeRecord.from_order_result(
                    result, direction="buy", amount_usd=amount_usd, is_test=is_test, reason=reason
                )
                await log_trade(record)
                await self._broadcast({
                    "type": "trade_executed",
                    "payload": {
                        "direction": "buy",
                        "pair": result.pair,
                        "quantity": result.quantity,
                        "price": result.price,
                        "amount_usd": amount_usd,
                        "order_id": result.order_id,
                        "executed_at": result.executed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "is_test": (binance_client._settings.trading_env == "testnet"),
                        "reason": reason,
                    },
                    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                })
                # Update balances after trade
                await self.update_balances(binance_client, config.trading_pair)
            except (BinanceOrderError, BinanceConnectionError) as e:
                logger.error("Buy order failed: %s", e)
                await self.set_error(str(e))

    async def _execute_sell(self, price: float, binance_client, reason: str = "signal") -> None:
        from src.services.binance_client import BinanceConnectionError, BinanceOrderError
        position = self.open_position
        if not position:
            return
        reason = reason or "signal"
        try:
            result = await binance_client.execute_market_sell(
                position.pair, position.quantity
            )
            logger.info(
                "%s sell: %s qty=%.6f price=%.2f",
                reason.replace("_", " ").capitalize(),
                position.pair, position.quantity, result.price,
            )
            is_test = (binance_client._settings.trading_env == "testnet")
            record = TradeRecord.from_order_result(
                result, direction="sell", amount_usd=position.quantity * result.price, is_test=is_test, reason=reason
            )
            await log_trade(record)
            # Clear position BEFORE broadcasting so all listeners see the correct cleared state
            self.open_position = None
            self._stop_loss_price = None
            self._take_profit_price = None
            self._last_rsi_was_oversold = False
            self._persist_state()
            logger.info("Broadcasting trade_executed for %s", reason)
            try:
                await self._broadcast({
                    "type": "trade_executed",
                    "payload": {
                        "direction": "sell",
                        "pair": result.pair,
                        "quantity": result.quantity,
                        "price": result.price,
                        "amount_usd": position.quantity * result.price,
                        "order_id": result.order_id,
                        "executed_at": result.executed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "entry_price": position.price,
                        "is_test": (binance_client._settings.trading_env == "testnet"),
                        "reason": reason
                    },
                    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                })
            except Exception as e:
                logger.error("Failed to broadcast trade_executed: %s", e)
            # Update balances after trade (position already cleared above)
            await self.update_balances(binance_client, position.pair)
        except (BinanceOrderError, BinanceConnectionError) as e:
            action_name = reason.replace("_", " ").capitalize() if reason else "Sell"
            logger.error("%s sell failed: %s", action_name, e)
            if "Insufficient balance" in str(e):
                logger.error("Insufficient balance - position kept open for manual resolution")
                await self.set_error(str(e))
            else:
                self.open_position = None
                self._stop_loss_price = None
                self._take_profit_price = None
                self._persist_state()
                await self.set_error(str(e))

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

    async def update_balances(self, binance_client, symbol: str) -> None:
        """Fetch latest balances and broadcast them."""
        self.balances = await binance_client.get_symbol_balances(symbol)
        await self._broadcast_state()

    async def _broadcast(self, message: dict) -> None:
        if self._broadcaster:
            await self._broadcaster.broadcast(message)
