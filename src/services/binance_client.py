from dataclasses import dataclass
from datetime import datetime, timezone

from binance import AsyncClient
from binance.exceptions import BinanceAPIException

from config.settings import Settings
from src.utils.logger import get_logger
from src.utils.retry import MaxRetriesExceededError, with_retry

logger = get_logger(__name__)


@dataclass
class OrderResult:
    order_id: str
    pair: str
    quantity: float
    price: float
    executed_at: datetime


class BinanceOrderError(Exception):
    pass


class BinanceConnectionError(Exception):
    """Raised when all retries are exhausted — signals a persistent API failure."""
    pass


class BinanceClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: AsyncClient | None = None

    async def connect(self) -> None:
        self._client = await AsyncClient.create(
            api_key=self._settings.binance_api_key,
            api_secret=self._settings.binance_api_secret,
            testnet=(self._settings.trading_env == "testnet"),
        )

    async def validate_connection(self) -> bool:
        try:
            await with_retry(self._client.get_account)
            return True
        except BinanceAPIException as e:
            logger.warning("Binance API error during validation: %s", e)
            return False
        except Exception as e:
            logger.warning("Unexpected error during Binance connection validation: %s", e)
            return False

    async def execute_market_buy(self, pair: str, amount_usd: float) -> OrderResult:
        """Place a market buy order for amount_usd worth of pair. No retry — use quoteOrderQty."""
        try:
            order = await self._client.create_order(
                symbol=pair,
                side="BUY",
                type="MARKET",
                quoteOrderQty=amount_usd,
            )
            fills = order.get("fills", [])
            avg_price = self._calculate_avg_price(fills) if fills else await self._get_fallback_price(pair)
            return OrderResult(
                order_id=str(order["orderId"]),
                pair=pair,
                quantity=float(order["executedQty"]),
                price=avg_price,
                executed_at=datetime.now(timezone.utc),
            )
        except Exception as e:
            raise BinanceOrderError(str(e)) from e

    async def execute_market_sell(self, pair: str, quantity: float) -> OrderResult:
        """Place a market sell order for exact quantity. No retry."""
        try:
            order = await self._client.create_order(
                symbol=pair,
                side="SELL",
                type="MARKET",
                quantity=quantity,
            )
            fills = order.get("fills", [])
            avg_price = self._calculate_avg_price(fills) if fills else await self._get_fallback_price(pair)
            return OrderResult(
                order_id=str(order["orderId"]),
                pair=pair,
                quantity=float(order["executedQty"]),
                price=avg_price,
                executed_at=datetime.now(timezone.utc),
            )
        except Exception as e:
            raise BinanceOrderError(str(e)) from e

    def _calculate_avg_price(self, fills: list) -> float:
        """Calculate weighted average price from all fills."""
        if not fills:
            return 0.0
        total_qty = 0.0
        total_cost = 0.0
        for fill in fills:
            qty = float(fill.get("qty", 0))
            price = float(fill.get("price", 0))
            total_qty += qty
            total_cost += qty * price
        return total_cost / total_qty if total_qty > 0 else 0.0

    async def _get_fallback_price(self, pair: str) -> float:
        """Get current price as fallback when fills array is empty."""
        try:
            ticker = await self._client.get_symbol_ticker(symbol=pair)
            return float(ticker["price"])
        except Exception:
            return 0.0

    async def get_current_price(self, pair: str) -> float:
        """Fetch the latest price for pair using retries. Raises BinanceConnectionError on exhaustion."""
        try:
            ticker = await with_retry(self._client.get_symbol_ticker, symbol=pair)
            return float(ticker["price"])
        except MaxRetriesExceededError as e:
            raise BinanceConnectionError(str(e.last_exception)) from e

    async def close(self) -> None:
        if self._client:
            await self._client.close_connection()
            self._client = None

    @property
    def client(self) -> AsyncClient | None:
        return self._client
