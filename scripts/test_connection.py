import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from config.settings import get_settings
from binance import AsyncClient
from src.services.binance_client import BinanceClient
from src.core.config_manager import load_config

async def test_env(env_name, api_key, api_secret, is_testnet):
    print(f"\n--- Testing {env_name.upper()} ---")
    print(f"Role: {'BUY/SELL Operations' if env_name == 'Trading' else 'All Other Info/Data'}")
    print(f"Environment: {'Testnet' if is_testnet else 'Mainnet'}")

    if not api_key or not api_secret or "your_" in api_key:
        print(f"⚠️ {env_name} keys are not configured in .env")
        return

    print(f"API Key: {api_key[:6]}...")

    try:
        client = await AsyncClient.create(
            api_key=api_key,
            api_secret=api_secret,
            testnet=is_testnet
        )
        acc = await client.get_account()
        print(f"✅ {env_name} Connection success! Account permissions: {acc.get('permissions', [])}")

        # Test a data fetch (Ticker)
        ticker = await client.get_symbol_ticker(symbol="BTCUSDT")
        print(f"📊 Recent BTC Price on {env_name}: ${ticker['price']}")

        await client.close_connection()
    except Exception as e:
        print(f"❌ {env_name} Connection failed: {e}")

async def test_history_fetch():
    print("\n--- Testing TRADE HISTORY FETCH (PROD) ---")
    settings = get_settings()
    config = load_config()
    client = BinanceClient(settings)
    await client.connect()
    try:
        trades = await client.get_trade_history(symbol=config.trading_pair, limit=5)
        if trades:
            print(f"✅ Successfully fetched {len(trades)} trades from PROD Binance account.")
            for t in trades[:3]:
                print(f"   - {t.executed_at}: {t.direction.upper()} {t.quantity} {t.pair} @ ${t.entry_price}")
        else:
            print("ℹ️ No trades found on the PROD account for this pair.")
    except Exception as e:
        print(f"❌ History fetch failed: {e}")
    finally:
        await client.close()

async def run_tests():
    settings = get_settings()

    print("Strict Role Verification:")
    print(f"TRADING_ENV is set to: {settings.trading_env.upper()}")

    # 1. Test Data connection (Always Prod)
    await test_env(
        "Data (PROD)",
        settings.prod_binance_api_key,
        settings.prod_binance_api_secret,
        False
    )

    # 2. Test Trading connection (Can be Testnet or Prod)
    await test_env(
        "Trading",
        settings.trading_api_key,
        settings.trading_api_secret,
        settings.trading_env == "testnet"
    )

    # 3. Test Real History Fetch (Must be Prod)
    await test_history_fetch()

if __name__ == "__main__":
    asyncio.run(run_tests())
