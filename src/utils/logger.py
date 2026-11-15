import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path


class CredentialFilter(logging.Filter):
    def __init__(self, sensitive_values: list[str]) -> None:
        super().__init__()
        self._sensitive = [v for v in sensitive_values if v and len(v) > 4]

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for secret in self._sensitive:
            msg = msg.replace(secret, "***")
        msg = re.sub(
            r"(?i)(api[_\-]?key|api[_\-]?secret|secret)[=:\s]+\S+",
            r"\1=***",
            msg,
        )
        record.msg = msg
        record.args = ()
        return True


_SECRET_FIELDS = (
    "prod_binance_api_key", "prod_binance_api_secret",
    "test_binance_api_key", "test_binance_api_secret",
    "live_binance_api_key", "live_binance_api_secret",
    "llm_api_key", "dashboard_token",
)


def collect_secrets(settings) -> list[str]:
    """Every configured secret value on a Settings object (empty ones are skipped by the filter)."""
    return [getattr(settings, name, "") or "" for name in _SECRET_FIELDS]


def setup_logging(api_key: str = "", api_secret: str = "", extra_secrets: list[str] | None = None) -> None:
    Path("logs").mkdir(exist_ok=True)

    cred_filter = CredentialFilter([api_key, api_secret, *(extra_secrets or [])])
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    file_handler = RotatingFileHandler(
        "logs/bot.log", maxBytes=10 * 1024 * 1024, backupCount=3
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(cred_filter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.addFilter(cred_filter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    # Avoid duplicate handlers on repeated calls (e.g. in tests)
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)


def get_logger(name: str, quiet: bool = False) -> logging.Logger:
    """Return a named logger.

    Args:
        name: Logger name (typically ``__name__``).
        quiet: When True the logger is set to WARNING so DEBUG/INFO messages
            are suppressed (only WARNING and above pass through to the root
            handlers). Use for hot paths that log on every tick or every trade
            so the log stays readable; warnings and errors always come through.
    """
    logger = logging.getLogger(name)
    if quiet:
        logger.setLevel(logging.WARNING)
    return logger
