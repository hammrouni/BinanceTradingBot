from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    binance_api_key: str
    binance_api_secret: str
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
