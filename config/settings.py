from functools import lru_cache

from pydantic import field_validator, model_validator
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

    # LLM config (chat endpoint)
    llm_base_url: str = "http://localhost:11434/v1"
    llm_model: str = "llama3.1"
    llm_api_key: str = "ollama"
    llm_timeout: int = 600
    llm_max_tokens: int = 16384

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("trading_env")
    @classmethod
    def validate_env(cls, v: str) -> str:
        if v not in ("testnet", "live"):
            raise ValueError("trading_env must be 'testnet' or 'live'")
        return v

    @model_validator(mode="after")
    def validate_live_keys(self) -> "Settings":
        if self.trading_env == "live":
            if not self.live_binance_api_key and not self.prod_binance_api_key:
                raise ValueError(
                    "No trading key available: set live_binance_api_key (or prod_binance_api_key as fallback) when trading_env is 'live'"
                )
            if not self.live_binance_api_key:
                import warnings
                warnings.warn(
                    "live_binance_api_key not set — falling back to prod_binance_api_key for live trading",
                    stacklevel=2,
                )
        return self

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
