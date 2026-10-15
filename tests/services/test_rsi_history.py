import pytest
from src.services.rsi_history_service import (
    add_rsi_threshold,
    get_rsi_threshold_history,
    clear_rsi_threshold_history,
    HISTORY_PATH
)

@pytest.fixture
def clean_history():
    # Setup
    if HISTORY_PATH.exists():
        HISTORY_PATH.unlink()
    yield
    # Teardown
    if HISTORY_PATH.exists():
        HISTORY_PATH.unlink()

def test_add_and_get_history(clean_history):
    # Add entries
    add_rsi_threshold("oversold", 30, "2026-03-28T10:00:00Z")
    add_rsi_threshold("overbought", 70, "2026-03-28T10:00:00Z")
    add_rsi_threshold("oversold", 25, "2026-03-28T11:00:00Z")

    # Get history
    history = get_rsi_threshold_history()
    assert len(history) == 3

    oversold = get_rsi_threshold_history("oversold")
    assert len(oversold) == 2
    assert oversold[0].value == 30
    assert oversold[1].value == 25
    assert oversold[1].timestamp == "2026-03-28T11:00:00Z"

def test_clear_history(clean_history):
    add_rsi_threshold("oversold", 30)
    add_rsi_threshold("overbought", 70)

    clear_rsi_threshold_history("oversold")
    history = get_rsi_threshold_history()
    assert len(history) == 1
    assert history[0].type == "overbought"

    clear_rsi_threshold_history()
    assert len(get_rsi_threshold_history()) == 0

def test_sorting(clean_history):
    # Add out of order
    add_rsi_threshold("oversold", 25, "2026-03-28T11:00:00Z")
    add_rsi_threshold("oversold", 30, "2026-03-28T10:00:00Z")

    history = get_rsi_threshold_history("oversold")
    assert history[0].value == 30
    assert history[1].value == 25
