from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    prod_binance_api_key: str
    prod_binance_api_secret: str
    test_binance_api_key: str
    test_binance_api_secret: str
    live_binance_api_key: str = ""
    live_binance_api_secret: str = ""
    trading_env: str = "testnet"
    trading_pair: str = "BTCUSDT"  # Default trading pair

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    @field_validator("trading_env")
    @classmethod
    def validate_env(cls, v: str) -> str:
        if v not in ("testnet", "live"):
            raise ValueError("trading_env must be 'testnet' or 'live'")
        return v

    @property
    def trading_api_key(self) -> str:
        if self.trading_env == "testnet":
            return self.test_binance_api_key
        return self.live_binance_api_key or self.prod_binance_api_key

    @property
    def trading_api_secret(self) -> str:
        if self.trading_env == "testnet":
            return self.test_binance_api_secret
        return self.live_binance_api_secret or self.prod_binance_api_secret


@lru_cache
def get_settings() -> Settings:
    return Settings()
