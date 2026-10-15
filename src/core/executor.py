"""executor.py — Logic to execute real-money and testnet trades.

Moves the execution of market buy/sell orders out of the BotEngine.
Uses the Binance client to place real orders and also handles trade logging.
"""

from __future__ import annotations

from datetime import datetime, timezone
import asyncio

from src.core.trade_logger import log_trade
from src.models.trade import TradeRecord
from src.utils.logger import get_logger

logger = get_logger(__name__)


class TradeExecutor:
    """Handles technical execution of market orders on Binance.

    Logs every trade (success or failure) and computes entry/exit metrics.
    """

    def __init__(self, binance_client, broadcaster=None) -> None:
        self._binance_client = binance_client
        self._broadcaster = broadcaster
        self.last_error: str | None = None  # message of the most recent failed order

    async def execute_buy(self, pair: str, amount_usd: float, reason: str = "buy_signal") -> "OrderResult" | None:
        """Execute a market buy order via the Binance client."""
        from src.services.binance_client import BinanceConnectionError, BinanceOrderError
        
        try:
            logger.info("Executing market BUY for %s: $%.2f (reason: %s)", pair, amount_usd, reason)
            result = await self._binance_client.execute_market_buy(pair, amount_usd)
            
            # Record in logs
            is_test = (self._binance_client._settings.trading_env == "testnet")
            record = TradeRecord.from_order_result(
                result, direction="buy", amount_usd=amount_usd, is_test=is_test, reason=reason
            )
            await log_trade(record)
            
            # Notify UI
            await self._broadcast_trade(result, "buy", amount_usd, is_test, reason)
            
            return result
        except (BinanceOrderError, BinanceConnectionError) as e:
            logger.error("Buy execution failed: %s", e)
            self.last_error = str(e)
            await self._broadcast_error("Buy order failed", str(e))
            return None

    async def execute_sell(self, pair: str, quantity: float, entry_price: float, reason: str = "signal") -> "OrderResult" | None:
        """Execute a market sell order via the Binance client."""
        from src.services.binance_client import BinanceConnectionError, BinanceOrderError
        
        try:
            logger.info("Executing market SELL for %s: qty %.6f (reason: %s)", pair, quantity, reason)
            result = await self._binance_client.execute_market_sell(pair, quantity)
            
            is_test = (self._binance_client._settings.trading_env == "testnet")
            amount_usd = quantity * result.price
            record = TradeRecord.from_order_result(
                result, direction="sell", amount_usd=amount_usd, is_test=is_test, reason=reason
            )
            await log_trade(record)
            
            # Notify UI
            await self._broadcast_trade(result, "sell", amount_usd, is_test, reason, entry_price=entry_price)
            
            return result
        except (BinanceOrderError, BinanceConnectionError) as e:
            logger.error("Sell execution failed: %s", e)
            # Handle specific Binance errors
            msg = str(e)
            self.last_error = msg
            if "UNSELLABLE_DUST" in msg:
                logger.warning("Unsellable dust detected after sell rejection")
            elif "insufficient available balance" in msg.lower():
                logger.warning("Sell rejected due balance mismatch")
            
            await self._broadcast_error("Sell order failed", msg)
            return None

    async def _broadcast_trade(self, result, direction, amount_usd, is_test, reason, entry_price=None):
        if not self._broadcaster:
            return
        
        payload = {
            "direction": direction,
            "pair": result.pair,
            "quantity": result.quantity,
            "price": result.price,
            "amount_usd": amount_usd,
            "order_id": result.order_id,
            "executed_at": result.executed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "is_test": is_test,
            "reason": reason,
        }
        if entry_price:
            payload["entry_price"] = entry_price
            
        await self._broadcaster.broadcast({
            "type": "trade_executed",
            "payload": payload,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })

    async def _broadcast_error(self, title, message):
        if self._broadcaster:
            await self._broadcaster.broadcast({
                "type": "error",
                "payload": {"code": "API_FAILURE", "message": f"{title}: {message}"},
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            })
