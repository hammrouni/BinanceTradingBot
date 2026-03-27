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


def setup_logging(api_key: str = "", api_secret: str = "") -> None:
    Path("logs").mkdir(exist_ok=True)

    cred_filter = CredentialFilter([api_key, api_secret])
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


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
