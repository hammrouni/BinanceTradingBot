import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

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
        self._last_rsi_was_oversold: bool = False
        self._broadcaster = broadcaster  # ConnectionManager injected at construction
        self._buy_in_progress: bool = False  # Guard against double-buy race
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
            logger.info("Bot state restored from disk: %s", self.state.value)
        except Exception as e:
            logger.warning("Could not restore bot state: %s", e)

    def _persist_state(self) -> None:
        """Write current state to disk so it survives restarts."""
        try:
            pos = self.open_position
            data: dict = {
                "state": self.state.value,
                "started_at": self.started_at.isoformat() if self.started_at else None,
                "stop_loss_price": self._stop_loss_price,
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
            logger.warning("Could not persist bot state: %s", e)

    @property
    def is_active(self) -> bool:
        return self.state == BotState.RUNNING

    async def start(self) -> None:
        if self.state not in (BotState.STOPPED, BotState.ERROR):
            raise InvalidStateTransitionError(f"Cannot start from {self.state}")
        self.state = BotState.RUNNING
        self.started_at = datetime.now(timezone.utc)
        self._last_rsi_was_oversold = False  # Reset RSI state on start
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
        self._last_rsi_was_oversold = False  # Reset RSI state on resume
        self._persist_state()
        logger.info("Bot resumed — state: RUNNING")
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

    def get_uptime_seconds(self) -> float:
        if self.started_at is None:
            return 0.0
        return (datetime.now(timezone.utc) - self.started_at).total_seconds()

    async def process_market_update(
        self,
        rsi: float | None,
        price: float,
        binance_client,
        config,
    ) -> None:
        """Process a market update tick: check stop-loss first, then buy signal."""
        # 1. Stop-loss check (protect capital) - works even when paused
        if (
            self.state in (BotState.RUNNING, BotState.PAUSED)
            and self.open_position is not None
            and self._stop_loss_price is not None
            and price < self._stop_loss_price
        ):
            await self._execute_sell(price, binance_client)
            return

        # 2. Buy signal — edge-triggered (only when running)
        if rsi is None:
            return

        is_oversold = rsi < config.rsi_threshold
        if (
            self.is_active
            and self.open_position is None
            and not self._buy_in_progress
            and is_oversold
            and not self._last_rsi_was_oversold
        ):
            await self._execute_buy(price, binance_client, config)

        self._last_rsi_was_oversold = is_oversold

    async def _execute_buy(self, price: float, binance_client, config) -> None:
        from src.services.binance_client import BinanceConnectionError, BinanceOrderError
        self._buy_in_progress = True
        try:
            result = await binance_client.execute_market_buy(
                config.trading_pair, config.trade_amount_usd
            )
            self.open_position = result
            self._stop_loss_price = result.price * (1 - config.stop_loss_pct / 100)
            self._persist_state()
            logger.info(
                "Buy executed: %s qty=%.6f price=%.2f stop-loss=%.2f",
                result.pair, result.quantity, result.price, self._stop_loss_price,
            )
            record = TradeRecord.from_order_result(result, direction="buy", amount_usd=config.trade_amount_usd)
            await log_trade(record)
            await self._broadcast({
                "type": "trade_executed",
                "payload": {
                    "direction": "buy",
                    "pair": result.pair,
                    "quantity": result.quantity,
                    "price": result.price,
                    "order_id": result.order_id,
                    "executed_at": result.executed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            })
        except (BinanceOrderError, BinanceConnectionError) as e:
            logger.error("Buy order failed: %s", e)
            await self.set_error(str(e))
        finally:
            self._buy_in_progress = False

    async def _execute_sell(self, price: float, binance_client) -> None:
        from src.services.binance_client import BinanceConnectionError, BinanceOrderError
        position = self.open_position
        if not position:
            return
        try:
            result = await binance_client.execute_market_sell(
                position.pair, position.quantity
            )
            logger.info(
                "Stop-loss sell: %s qty=%.6f price=%.2f",
                position.pair, position.quantity, result.price,
            )
            record = TradeRecord.from_order_result(result, direction="sell", amount_usd=position.quantity * result.price)
            await log_trade(record)
            await self._broadcast({
                "type": "trade_executed",
                "payload": {
                    "direction": "sell",
                    "pair": result.pair,
                    "quantity": result.quantity,
                    "price": result.price,
                    "order_id": result.order_id,
                    "executed_at": result.executed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "entry_price": position.price,
                },
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            })
            self.open_position = None
            self._stop_loss_price = None
            self._last_rsi_was_oversold = False
            self._persist_state()
        except (BinanceOrderError, BinanceConnectionError) as e:
            logger.error("Stop-loss sell failed: %s", e)
            # Clear position to prevent retry storm - the order may have succeeded despite the error
            self.open_position = None
            self._stop_loss_price = None
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
                    } if self.open_position else None,
                },
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            })

    async def _broadcast(self, message: dict) -> None:
        if self._broadcaster:
            await self._broadcaster.broadcast(message)
