"""position_manager.py — Logic to recover, reconcile and sync open positions.

Ensures the bot knows its actual exposed position by syncing local state with Binance.
"""

from __future__ import annotations

from datetime import datetime, timezone
import asyncio

from src.core.trade_reader import read_trades
from src.utils.logger import get_logger

logger = get_logger(__name__)


class PositionManager:
    """Handles technical syncing of open positions between the bot and Binance."""

    def __init__(self, binance_client, broadcaster=None) -> None:
        self._binance_client = binance_client
        self._broadcaster = broadcaster

    def _is_testnet(self) -> bool:
        """True when the client trades on testnet, i.e. the trade log entries that belong to this bot are is_test."""
        settings = getattr(self._binance_client, "_settings", None)
        return getattr(settings, "trading_env", "testnet") == "testnet"

    async def get_base_asset_balance(self, symbol: str) -> float:
        """Fetch the current base asset total from Binance.

        Raises if the balance cannot be read: 0.0 must only ever mean "confirmed empty".
        """
        balance = await self._binance_client.get_base_asset_balance(symbol)
        return float(balance.get("total", 0.0))

    async def get_step_size(self, symbol: str) -> float | None:
        """Fetch the LOT_SIZE step size for a given symbol."""
        try:
            get_step = getattr(self._binance_client, "_get_step_size", None)
            if callable(get_step):
                raw_step = await get_step(symbol)
                if raw_step is not None:
                    return float(raw_step)
        except Exception:
            pass
        return None

    def find_recoverable_open_trade(self, symbol: str, wallet_quantity: float) -> "TradeRecord" | None:
        """Find the best unmatched BUY of this pair and environment (testnet or live) to rebuild the wallet position.

        Only trades of the same pair and the same environment as the client take part, so neither
        another pair's sells nor the other environment's trades can close or fake a position.
        """
        testnet = self._is_testnet()
        trades = [
            trade for trade in read_trades(limit=500)
            if trade.pair == symbol and trade.is_test == testnet
        ]
        if not trades:
            return None

        chronological = sorted(trades, key=lambda trade: trade.executed_at)
        open_buys = []
        for trade in chronological:
            if trade.direction == "buy":
                open_buys.append(trade)
            elif trade.direction == "sell" and open_buys:
                open_buys.pop(0)

        if not open_buys:
            return None

        best_match = None
        best_diff = None
        for trade in open_buys:
            diff = abs(trade.quantity - wallet_quantity)
            if best_match is None or diff <= best_diff:
                best_match = trade
                best_diff = diff
        return best_match

    async def recover_open_position(self, symbol: str) -> "OrderResult" | None:
        """Rebuild an open position from wallet balance + trade log when persisted state is missing."""
        try:
            total_balance = await self.get_base_asset_balance(symbol)
            if total_balance <= 0:
                return None

            # Ignore tiny dust balances that cannot be sold on Binance (below LOT_SIZE step).
            step_size = await self.get_step_size(symbol)
            if step_size and 0 < total_balance < step_size:
                logger.warning(
                    "Skipping open position recovery for %s: wallet balance %.12f is unsellable dust (stepSize=%.12f)",
                    symbol, total_balance, step_size
                )
                return None

            trade = self.find_recoverable_open_trade(symbol, total_balance)
            if trade is None:
                logger.warning(
                    "Wallet holds %.12f %s but no unmatched BUY trade was found to recover open position",
                    total_balance, symbol
                )
                return None

            from src.core.bot_engine import OrderResult
            return OrderResult(
                order_id=trade.order_id,
                pair=trade.pair,
                quantity=min(total_balance, trade.quantity),
                price=trade.entry_price,
                executed_at=datetime.fromisoformat(trade.executed_at.replace("Z", "+00:00")),
            )
        except Exception as e:
            logger.warning("Could not recover open position: %s", e)
            return None

    async def reconcile_open_position(self, current_pos, symbol: str) -> tuple["OrderResult" | None, bool]:
        """Check the bot-owned position against the wallet.

        `current_pos.quantity` is what the bot bought. The wallet may hold more (pre-existing coins):
        that surplus is never adopted. The quantity is only ever reduced, when the wallet holds less.

        Returns:
            (new_position, changed); (None, True) means the position is confirmed gone.

        Raises:
            Any error from reading the balance. The caller must keep the position in that case.
        """
        if current_pos is None:
            return None, False

        total_balance = await self.get_base_asset_balance(symbol)

        # Clear unsellable dust positions
        step_size = await self.get_step_size(symbol)
        if step_size and 0 < total_balance < step_size:
            logger.warning(
                "Clearing open position for %s: wallet total %.12f is unsellable dust (stepSize=%.12f)",
                symbol, total_balance, step_size
            )
            return None, True

        if total_balance <= 0:
            logger.warning("Clearing stale open position for %s because the wallet confirms no base asset", symbol)
            return None, True

        if total_balance < current_pos.quantity - 1e-10:
            logger.warning(
                "Reducing open position quantity for %s from %.12f to wallet total %.12f",
                symbol, current_pos.quantity, total_balance
            )
            current_pos.quantity = total_balance
            return current_pos, True

        return current_pos, False
