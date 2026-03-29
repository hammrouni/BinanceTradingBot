from dataclasses import dataclass
from datetime import datetime, timezone

from binance import AsyncClient
from binance.exceptions import BinanceAPIException

from config.settings import Settings
from src.models.trade import TradeRecord
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
        self._trading_client: AsyncClient | None = None
        self._data_client: AsyncClient | None = None
        self._symbol_info_cache: dict[str, dict] = {}

    async def connect(self) -> None:
        # Client for actual order execution (can be TESTNET or LIVE)
        self._trading_client = await AsyncClient.create(
            api_key=self._settings.trading_api_key,
            api_secret=self._settings.trading_api_secret,
            testnet=(self._settings.trading_env == "testnet"),
        )
        # Client for market data and info (ALWAYS PROD/LIVE)
        self._data_client = await AsyncClient.create(
            api_key=self._settings.prod_binance_api_key,
            api_secret=self._settings.prod_binance_api_secret,
            testnet=False,
        )

    async def validate_connection(self) -> bool:
        """Validate both connections (Trading and Data)."""
        try:
            # Check market data (PROD)
            await with_retry(self._data_client.get_account)
            # Check trading account (TEST or PROD)
            await with_retry(self._trading_client.get_account)
            return True
        except BinanceAPIException as e:
            logger.warning("Binance API error during validation: %s", e)
            return False
        except Exception as e:
            logger.warning("Unexpected error during Binance connection validation: %s", e)
            return False

    async def execute_market_buy(self, pair: str, amount_usd: float) -> OrderResult:
        """Place a market buy order using the TRADING client."""
        try:
            order = await self._trading_client.create_order(
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
        """Place a market sell order using the TRADING client."""
        try:
            balance = await self.get_base_asset_balance(pair)
            available_qty = balance["free"]
            sell_qty = min(quantity, available_qty)

            if sell_qty <= 0:
                raise BinanceOrderError(
                    f"Insufficient available balance for {pair}: requested={quantity}, available={available_qty}"
                )

            if sell_qty < quantity:
                logger.warning(
                    "Reducing SELL quantity for %s from %.12f to available %.12f",
                    pair,
                    quantity,
                    sell_qty,
                )

            # Fix: Format quantity correctly to avoid -1100 and -1013 NOTIONAL errors
            formatted_qty = await self._format_quantity(pair, sell_qty)
            formatted_qty_value = float(formatted_qty)

            if formatted_qty_value <= 0:
                raise BinanceOrderError(
                    f"Formatted sell quantity is zero for {pair}: requested={quantity}, available={available_qty}"
                )
            
            # Double check notional value
            price = await self.get_current_price(pair)
            notional = formatted_qty_value * price
            min_notional = await self._get_min_notional(pair)
            
            if min_notional and notional < min_notional:
                logger.warning("Order rejected: Notional %f is below minimum %f for %s", notional, min_notional, pair)
                raise BinanceOrderError(f"Filter failure: NOTIONAL (Min: {min_notional}, Current: {notional:.2f})")

            logger.info("Executing SELL for %s: qty=%s (notional=$%.2f)", pair, formatted_qty, notional)

            order = await self._trading_client.create_order(
                symbol=pair,
                side="SELL",
                type="MARKET",
                quantity=formatted_qty,
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

    async def get_base_asset_balance(self, symbol: str) -> dict[str, float]:
        """Return free, locked and total balance for the symbol's base asset on the trading account."""
        info = await self._get_cached_info(symbol)
        if not info:
            return {"free": 0.0, "locked": 0.0, "total": 0.0}

        base_asset = info.get("baseAsset")
        if not base_asset:
            return {"free": 0.0, "locked": 0.0, "total": 0.0}

        account = await self._trading_client.get_account()
        for balance in account.get("balances", []):
            if balance.get("asset") == base_asset:
                free = float(balance.get("free", 0.0))
                locked = float(balance.get("locked", 0.0))
                return {"free": free, "locked": locked, "total": free + locked}

        return {"free": 0.0, "locked": 0.0, "total": 0.0}

    async def _format_quantity(self, symbol: str, quantity: float) -> str:
        """Format quantity based on symbol's stepSize filter."""
        step_size = await self._get_step_size(symbol)
        if not step_size:
            return str(quantity)
        
        # Calculate precision from stepSize (e.g. 0.001 -> 3)
        import math
        precision = int(round(-math.log10(float(step_size))))
        
        # Floor the quantity to the required precision
        # FIX: Add a small epsilon (1e-10) to avoid binary precision artifacts 
        # (e.g. 0.00007 being represented as 0.069999999999 which math.floor makes 0.00006)
        factor = 10 ** precision
        eps = 1e-10 / factor
        floored = math.floor((quantity + eps) * factor) / factor
        return "{:0.{}f}".format(floored, precision)

    async def _get_min_notional(self, symbol: str) -> float | None:
        """Fetch and cache symbol minNotional from exchangeInfo."""
        info = await self._get_cached_info(symbol)
        if not info:
            return None
        
        for f in info.get("filters", []):
            if f["filterType"] == "NOTIONAL":
                return float(f["minNotional"])
        return None

    async def _get_step_size(self, symbol: str) -> float | None:
        """Fetch and cache symbol stepSize from exchangeInfo."""
        info = await self._get_cached_info(symbol)
        if not info:
            return None
        
        for f in info.get("filters", []):
            if f["filterType"] == "LOT_SIZE":
                return float(f["stepSize"])
        return None

    async def _get_cached_info(self, symbol: str) -> dict | None:
        """Fetch and cache symbol exchangeInfo if not present."""
        if symbol not in self._symbol_info_cache:
            try:
                info = await self._data_client.get_symbol_info(symbol=symbol)
                if info:
                    self._symbol_info_cache[symbol] = info
            except Exception as e:
                logger.error("Error fetching symbol info for %s: %s", symbol, e)
                return None
        return self._symbol_info_cache.get(symbol)

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
        """Get current price as fallback when fills array is empty (from DATA client)."""
        try:
            ticker = await self._data_client.get_symbol_ticker(symbol=pair)
            return float(ticker["price"])
        except Exception:
            return 0.0

    async def get_current_price(self, pair: str) -> float:
        """Fetch the latest price for pair (from DATA client)."""
        try:
            ticker = await with_retry(self._data_client.get_symbol_ticker, symbol=pair)
            return float(ticker["price"])
        except MaxRetriesExceededError as e:
            raise BinanceConnectionError(str(e.last_exception)) from e

    async def get_symbol_balances(self, symbol: str) -> dict[str, dict]:
        """Fetch all available balances and calculate total net worth for both PROD and TRADING clients."""
        try:
            # Fetch all tickers for price conversion (always from DATA client)
            tickers = await self._data_client.get_all_tickers()
            prices = {t["symbol"]: float(t["price"]) for t in tickers}
            prices["USDT"] = 1.0  # Base unit

            async def _fetch_and_calculate(client):
                try:
                    acc = await client.get_account()
                    balances = acc.get("balances", [])
                    
                    assets = {}
                    total_usdt = 0.0
                    
                    for b in balances:
                        free = float(b["free"])
                        locked = float(b["locked"])
                        total = free + locked
                        
                        if total > 0:
                            asset_name = b["asset"]
                            assets[asset_name] = {"free": free, "locked": locked}
                            
                            # Calculate USD value for the assets we can price
                            if asset_name == "USDT":
                                total_usdt += total
                            elif f"{asset_name}USDT" in prices:
                                total_usdt += total * prices[f"{asset_name}USDT"]
                            elif f"USDT{asset_name}" in prices:
                                total_usdt += total / prices[f"USDT{asset_name}"]
                            elif f"{asset_name}BTC" in prices and "BTCUSDT" in prices:
                                total_usdt += total * prices[f"{asset_name}BTC"] * prices["BTCUSDT"]
                    
                    return {
                        "assets": assets,
                        "total_net_worth": round(total_usdt, 2)
                    }
                except Exception as e:
                    logger.warning("Sub-account balance fetch failed: %s", e)
                    return {"assets": {}, "total_net_worth": 0.0}

            prod_data = await _fetch_and_calculate(self._data_client)
            trading_data = await _fetch_and_calculate(self._trading_client)
            
            return {
                "prod": prod_data,
                "trading": trading_data,
                "trading_env": self._settings.trading_env
            }
        except Exception as e:
            logger.error("Error fetching comprehensive balances: %s", e)
            return {}

    async def get_trade_history(self, symbol: str, limit: int = 50) -> list[TradeRecord]:
        """Fetch recent trade history from the PROD/Data client."""
        try:
            trades = await self._data_client.get_my_trades(symbol=symbol, limit=limit)
            records = []
            for t in trades:
                records.append(TradeRecord(
                    id=str(t["id"]),
                    executed_at=datetime.fromtimestamp(t["time"] / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    pair=symbol,
                    direction="buy" if t["isBuyer"] else "sell",
                    amount_usd=float(t["quoteQty"]),
                    quantity=float(t["qty"]),
                    entry_price=float(t["price"]),
                    order_id=str(t["orderId"]),
                ))
            # Reverse to newest first
            records.reverse()
            return records
        except Exception as e:
            logger.error("Error fetching trade history from PROD: %s", e)
            return []

    async def close(self) -> None:
        if self._trading_client:
            await self._trading_client.close_connection()
            self._trading_client = None
        if self._data_client:
            await self._data_client.close_connection()
            self._data_client = None

    @property
    def client(self) -> AsyncClient | None:
        """Returns the DATA client by default for general usage."""
        return self._data_client
