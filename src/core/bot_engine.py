import asyncio
import json
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from src.models.config import TradingConfig
from src.core.trade_logger import log_trade
from src.core.trade_reader import read_trades
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
        self._last_bc_buy_triggered: bool = False
        self._last_bc_sell_triggered: bool = False
        self._broadcaster = broadcaster  # ConnectionManager injected at construction
        self._buy_lock: asyncio.Lock = asyncio.Lock()  # Guard against concurrent buys
        self.balances: dict = {
            "prod": {"assets": {}, "total_net_worth": 0.0},
            "trading": {"assets": {}, "total_net_worth": 0.0},
            "trading_env": "testnet"
        }
        self.market_history: deque[dict] = deque(maxlen=1000)
        self._trailing_stop_high: float | None = None  # highest price seen while in position
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
        self._last_bc_buy_triggered = False
        self._last_bc_sell_triggered = False
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
        self._last_bc_buy_triggered = False
        self._last_bc_sell_triggered = False
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
        self._last_bc_buy_triggered = False
        self._last_bc_sell_triggered = False
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
        
        # SL calculation — preserve trailing stop if it's already higher than the fixed SL
        new_fixed_sl = (
            self.open_position.price * (1 - config.stop_loss_pct / 100)
            if config.stop_loss_pct is not None else None
        )
        new_trailing_sl = (
            self.open_position.price * (1 - config.trailing_stop_pct / 100)
            if config.trailing_stop_pct is not None else None
        )
        candidates = [s for s in (new_fixed_sl, new_trailing_sl, self._stop_loss_price) if s is not None]
        self._stop_loss_price = max(candidates) if candidates else None

        # TP calculation — anchor to min_bc_price in BC mode, else use actual entry price
        if config.take_profit_pct is not None and config.take_profit_pct > 0:
            tp_base = config.min_bc_price if config.min_bc_price is not None else self.open_position.price
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

        # 0. Trailing stop — ratchet SL upward with price (never downward)
        if (
            self.open_position is not None
            and config.trailing_stop_pct is not None
            and self._stop_loss_price is not None
        ):
            new_trailing = price * (1 - config.trailing_stop_pct / 100)
            if new_trailing > self._stop_loss_price:
                logger.info(
                    "Trailing stop ratcheted: %.2f → %.2f (price=%.2f trail=%.2f%%)",
                    self._stop_loss_price, new_trailing, price, config.trailing_stop_pct,
                )
                self._stop_loss_price = new_trailing
                self._persist_state()

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
            config.min_bc_price is not None
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

        # 2. Buy / Sell signals — mode-dependent (multi-mode support)
        active_modes = getattr(config, 'active_modes', None) or ['RSI']

        if 'BC' in active_modes:
            # ─── BC MODE: price-target signals ──────────────────────────────
            bc_buy  = getattr(config, 'bc_buy_price',  None)
            bc_sell = getattr(config, 'bc_sell_price', None)

            if (
                self.is_active
                and self.open_position is None
                and not self._buy_lock.locked()
                and bc_buy is not None
                and price <= bc_buy
                and not self._last_bc_buy_triggered
            ):
                logger.info("BC Mode: price %.2f reached buy target %.2f", price, bc_buy)
                amount_override = None if config.trade_amount_usd else self._get_available_usdt()
                if amount_override is None or amount_override >= 1.0:
                    await self._execute_buy(price, binance_client, config, reason="bc_buy_target",
                                            amount_override=amount_override)

            elif (
                self.is_active
                and self.open_position is not None
                and bc_sell is not None
                and self._take_profit_price is None
                and price >= bc_sell
                and not self._last_bc_sell_triggered
            ):
                logger.info("BC Mode: price %.2f reached sell target %.2f", price, bc_sell)
                await self._execute_sell(price, binance_client, reason="bc_sell_target")

            self._last_bc_buy_triggered  = bc_buy  is not None and price <= bc_buy
            self._last_bc_sell_triggered = bc_sell is not None and price >= bc_sell

        if 'RSI' in active_modes:
            # ─── RSI MODE ───────────────────────────────────────────────────
            if rsi is None:
                return

            is_oversold = False
            if config.rsi_oversold is not None:
                is_oversold = rsi < config.rsi_oversold

            is_overbought = False
            if config.rsi_overbought is not None:
                is_overbought = rsi > config.rsi_overbought

            # BUY SIGNAL
            if (
                self.is_active
                and self.open_position is None
                and not self._buy_lock.locked()
                and config.trade_amount_usd is not None
                and config.rsi_oversold is not None
                and is_oversold
                and not self._last_rsi_was_oversold
                and (config.price_bounce_ticks is None or self._is_price_bouncing(config.price_bounce_ticks))
                and not self._is_bear_trend(config.bear_trend_candles, config.bear_trend_pct)
            ):
                logger.info("RSI Oversold signal detected (%.2f < %s)", rsi, config.rsi_oversold)
                await self._execute_buy(price, binance_client, config, reason="buy_signal")

            # SELL SIGNAL (RSI)
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

            self._last_rsi_was_oversold  = is_oversold
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
                # Initial SL: use fixed SL if configured, else seed from trailing_stop_pct
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
            self._last_rsi_was_overbought = False
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
            # Update balances after state is cleared so UI receives a consistent bot_status payload.
            await self.update_balances(binance_client, position.pair)
        except (BinanceOrderError, BinanceConnectionError) as e:
            action_name = reason.replace("_", " ").capitalize() if reason else "Sell"
            message = str(e)
            message_lower = message.lower()
            logger.error("%s sell failed: %s", action_name, message)

            # If remaining wallet balance is below Binance lot step-size, dust cannot be sold.
            # Clear stale local position and continue running.
            if "UNSELLABLE_DUST" in message:
                logger.warning("Unsellable dust detected after sell rejection; clearing local open position")
                self.open_position = None
                self._stop_loss_price = None
                self._take_profit_price = None
                self._last_rsi_was_oversold = False
                self._last_rsi_was_overbought = False
                self._persist_state()
                await self.update_balances(binance_client, position.pair)
                return

            # Wallet/order quantity mismatch can happen after partial/manual sells or fee effects.
            # Reconcile from wallet and keep bot running instead of forcing ERROR state.
            if "insufficient available balance" in message_lower or "insufficient balance" in message_lower:
                logger.warning("Sell rejected due balance mismatch; reconciling open position with wallet")
                await self.reconcile_open_position(binance_client, position.pair)
                await self.update_balances(binance_client, position.pair)
                return

            self.open_position = None
            self._stop_loss_price = None
            self._take_profit_price = None
            self._persist_state()
            await self.set_error(message)

    # ─── Feature helpers ──────────────────────────────────────────────────────

    def _is_price_bouncing(self, ticks: int) -> bool:
        """Return True if the last `ticks` price observations show an upward move.

        If there is not enough history yet the filter is skipped (returns True)
        so the bot is not blocked at startup.
        """
        if len(self.market_history) < ticks + 1:
            return True  # not enough data — don't block buy
        prices = [entry["price"] for entry in list(self.market_history)[-(ticks + 1):]]
        return prices[-1] > prices[0]

    def _is_bear_trend(self, candles: int | None, pct: float | None) -> bool:
        """Return True if price dropped more than `pct`% over the last `candles` ticks.

        Both parameters must be non-None; otherwise the filter is disabled.
        """
        if candles is None or pct is None:
            return False
        if len(self.market_history) < candles:
            return False  # not enough history — don't block buy
        history_list = list(self.market_history)
        past_price = history_list[-candles]["price"]
        current_price = history_list[-1]["price"]
        if past_price <= 0:
            return False
        drop_pct = (past_price - current_price) / past_price * 100
        if drop_pct >= pct:
            logger.info(
                "Bear trend filter active: price dropped %.2f%% over last %d ticks (%.2f → %.2f)",
                drop_pct, candles, past_price, current_price,
            )
            return True
        return False

    def _find_recoverable_open_trade(self, symbol: str, wallet_quantity: float) -> TradeRecord | None:
        """Find the best unmatched real BUY trade to reconstruct the current wallet position."""
        trades = [
            trade for trade in read_trades(limit=500)
            if trade.pair == symbol and not trade.is_test
        ]
        if not trades:
            return None

        chronological = sorted(trades, key=lambda trade: trade.executed_at)
        open_buys: list[TradeRecord] = []
        for trade in chronological:
            if trade.direction == "buy":
                open_buys.append(trade)
            elif trade.direction == "sell" and open_buys:
                open_buys.pop(0)

        if not open_buys:
            return None

        best_match: TradeRecord | None = None
        best_diff: float | None = None
        for trade in open_buys:
            diff = abs(trade.quantity - wallet_quantity)
            if best_match is None or diff <= best_diff:
                best_match = trade
                best_diff = diff
        return best_match

    async def recover_open_position(self, binance_client, symbol: str) -> None:
        """Rebuild an open position from wallet balance + trade log when persisted state is missing."""
        if self.open_position is not None:
            return

        try:
            balance = await binance_client.get_base_asset_balance(symbol)
            total_balance = balance["total"]
            if total_balance <= 0:
                return

            # Ignore tiny dust balances that cannot be sold on Binance (below LOT_SIZE step).
            step_size = None
            get_step_size = getattr(binance_client, "_get_step_size", None)
            if callable(get_step_size):
                try:
                    raw_step = await get_step_size(symbol)
                    if raw_step is not None:
                        step_size = float(raw_step)
                except Exception:
                    step_size = None

            if step_size and 0 < total_balance < step_size:
                logger.warning(
                    "Skipping open position recovery for %s: wallet balance %.12f is unsellable dust (stepSize=%.12f)",
                    symbol,
                    total_balance,
                    step_size,
                )
                return

            trade = self._find_recoverable_open_trade(symbol, total_balance)
            if trade is None:
                logger.warning(
                    "Wallet holds %.12f %s but no unmatched BUY trade was found to recover open position",
                    total_balance,
                    symbol,
                )
                return

            self.open_position = OrderResult(
                order_id=trade.order_id,
                pair=trade.pair,
                quantity=min(total_balance, trade.quantity),
                price=trade.entry_price,
                executed_at=datetime.fromisoformat(trade.executed_at.replace("Z", "+00:00")),
            )
            logger.warning(
                "Recovered open position for %s from trade log: qty=%.12f entry=%.2f order_id=%s",
                trade.pair,
                self.open_position.quantity,
                self.open_position.price,
                self.open_position.order_id,
            )
            self._persist_state()
        except Exception as e:
            logger.warning("Could not recover open position from wallet/trade log: %s", e)

    async def reconcile_open_position(self, binance_client, symbol: str) -> None:
        """Sync persisted position state with the actual trading wallet balance."""
        if self.open_position is None:
            return

        try:
            balance = await binance_client.get_base_asset_balance(symbol)
            total_balance = balance["total"]

            # Clear unsellable dust positions so stop-loss/TP won't keep retrying impossible sells.
            step_size = None
            get_step_size = getattr(binance_client, "_get_step_size", None)
            if callable(get_step_size):
                try:
                    raw_step = await get_step_size(symbol)
                    if raw_step is not None:
                        step_size = float(raw_step)
                except Exception:
                    step_size = None

            if step_size and 0 < total_balance < step_size:
                logger.warning(
                    "Clearing open position for %s: wallet total %.12f is unsellable dust (stepSize=%.12f)",
                    symbol,
                    total_balance,
                    step_size,
                )
                self.open_position = None
                self._stop_loss_price = None
                self._take_profit_price = None
                self._persist_state()
                return

            if total_balance <= 0:
                logger.warning(
                    "Clearing stale open position for %s because no base asset balance exists on Binance",
                    symbol,
                )
                self.open_position = None
                self._stop_loss_price = None
                self._persist_state()
                return

            if total_balance < self.open_position.quantity:
                logger.warning(
                    "Reducing open position quantity for %s from %.12f to wallet total %.12f",
                    symbol,
                    self.open_position.quantity,
                    total_balance,
                )
                self.open_position.quantity = total_balance
                self._persist_state()
        except Exception as e:
            logger.warning("Could not reconcile open position with Binance wallet: %s", e)

    async def sync_open_position(self, binance_client, config: TradingConfig) -> None:
        """Ensure in-memory position matches the real wallet before the bot trades again."""
        if self.open_position is None:
            await self.recover_open_position(binance_client, config.trading_pair)

        if self.open_position is not None:
            await self.reconcile_open_position(binance_client, config.trading_pair)
            await self.refresh_thresholds(config)

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

    async def update_balances(self, binance_client, symbol: str, config: TradingConfig | None = None) -> None:
        """Fetch latest balances and broadcast them."""
        self.balances = await binance_client.get_symbol_balances(symbol)
        if config is not None:
            await self.sync_open_position(binance_client, config)
        await self._broadcast_state()

    async def _broadcast(self, message: dict) -> None:
        if self._broadcaster:
            await self._broadcaster.broadcast(message)
