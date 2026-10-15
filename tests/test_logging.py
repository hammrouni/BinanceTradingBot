"""Tests for Stories 1.3 and 6.4: Credential-Safe Logging Infrastructure."""
import logging
from unittest.mock import patch

from src.utils.logger import CredentialFilter, setup_logging


def make_record(msg: str, args: tuple = ()) -> logging.LogRecord:
    return logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg=msg,
        args=args,
        exc_info=None,
    )


def test_direct_api_key_value_is_masked():
    cred_filter = CredentialFilter(["my_real_api_key_abc123", "my_real_secret_xyz789"])
    record = make_record("Connecting with key my_real_api_key_abc123")
    cred_filter.filter(record)
    assert "my_real_api_key_abc123" not in record.msg
    assert "***" in record.msg


def test_direct_api_secret_value_is_masked():
    cred_filter = CredentialFilter(["my_real_api_key_abc123", "my_real_secret_xyz789"])
    record = make_record("Secret: my_real_secret_xyz789")
    cred_filter.filter(record)
    assert "my_real_secret_xyz789" not in record.msg
    assert "***" in record.msg


def test_non_credential_message_passes_unchanged():
    cred_filter = CredentialFilter(["secret_key_value", "secret_secret_value"])
    record = make_record("Bot started successfully")
    cred_filter.filter(record)
    assert record.msg == "Bot started successfully"


def test_key_value_pattern_is_masked():
    cred_filter = CredentialFilter([])
    record = make_record("Config: api_key=supersecretvalue123")
    cred_filter.filter(record)
    assert "supersecretvalue123" not in record.msg
    assert "api_key=***" in record.msg


def test_api_secret_key_value_pattern_is_masked():
    cred_filter = CredentialFilter([])
    record = make_record("Loaded api_secret=topsecretvalue456")
    cred_filter.filter(record)
    assert "topsecretvalue456" not in record.msg
    assert "***" in record.msg


def test_record_args_cleared_after_filter():
    cred_filter = CredentialFilter(["my_real_api_key_abc123"])
    record = make_record("key=%s", args=("my_real_api_key_abc123",))
    cred_filter.filter(record)
    assert record.args == ()


def test_short_values_not_filtered():
    """Values <= 4 chars are excluded to avoid masking common strings."""
    cred_filter = CredentialFilter(["key", "abc"])
    record = make_record("Normal message with key and abc words")
    cred_filter.filter(record)
    assert "Normal message" in record.msg


# ---------------------------------------------------------------------------
# Story 6.4: Logger infrastructure verification (AC: 1, 2, 3)
# ---------------------------------------------------------------------------


def test_setup_logging_creates_rotating_file_handler():
    """setup_logging() must add a RotatingFileHandler with 10MB max and 3 backups."""
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    try:
        with patch("src.utils.logger.RotatingFileHandler") as mock_rfh, \
             patch("src.utils.logger.Path") as MockPath:
            MockPath.return_value.mkdir = lambda **kw: None
            mock_rfh.return_value = logging.NullHandler()
            setup_logging(api_key="key", api_secret="secret")
            mock_rfh.assert_called_once()
            kwargs = mock_rfh.call_args.kwargs
            assert kwargs.get("maxBytes", 0) >= 10_000_000, (
                f"maxBytes must be >= 10MB, got {kwargs.get('maxBytes')}"
            )
            assert kwargs.get("backupCount") == 3, (
                f"backupCount must be 3, got {kwargs.get('backupCount')}"
            )
    finally:
        root.handlers.clear()
        for h in original_handlers:
            root.addHandler(h)


def test_setup_logging_applies_credential_filter_to_both_handlers():
    """CredentialFilter must be applied to both StreamHandler and RotatingFileHandler."""
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    try:
        with patch("src.utils.logger.RotatingFileHandler") as mock_rfh, \
             patch("src.utils.logger.Path") as MockPath:
            MockPath.return_value.mkdir = lambda **kw: None
            captured_filters = []

            class TrackingNullHandler(logging.NullHandler):
                def addFilter(self, f):
                    captured_filters.append(f)
                    super().addFilter(f)

            mock_rfh.return_value = TrackingNullHandler()
            setup_logging(api_key="longapikey123", api_secret="longsecret456")

        # Check that CredentialFilter was applied to the file handler
        assert any(isinstance(f, CredentialFilter) for f in captured_filters), (
            "CredentialFilter must be applied to RotatingFileHandler"
        )
        # Check StreamHandler in root logger also has CredentialFilter
        stream_handlers_with_filter = [
            h for h in root.handlers
            if isinstance(h, logging.StreamHandler)
            and any(isinstance(f, CredentialFilter) for f in h.filters)
        ]
        assert stream_handlers_with_filter, "CredentialFilter must be applied to StreamHandler"
    finally:
        root.handlers.clear()
        for h in original_handlers:
            root.addHandler(h)
