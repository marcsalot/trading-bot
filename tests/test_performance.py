"""
Tests for performance.py — compute_metrics().

All tests use synthetic trade DataFrames with known values so results
can be verified by hand without running a real backtest.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from performance import compute_metrics  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _trades(*rows):
    """Build a minimal trades DataFrame from (raw_return, alpha) tuples."""
    return pd.DataFrame(
        [{"ticker": "X", "date": "2024-01-01", "signal": "Buy",
          "multiplier": 1.0, "entry_price": 100.0, "exit_price": 100.0,
          "raw_return": r, "spy_return": 0.0, "alpha": a}
         for r, a in rows]
    )


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------

class TestEmptyTrades:
    def test_returns_empty_dict(self):
        assert compute_metrics(pd.DataFrame()) == {}


# ---------------------------------------------------------------------------
# Single trade
# ---------------------------------------------------------------------------

class TestSingleTrade:
    TRADES = _trades((0.10, 0.05))

    def test_total_trades_is_1(self):
        assert compute_metrics(self.TRADES)["total_trades"] == 1

    def test_total_return_equals_raw_return(self):
        # One trade compounded: (1 + 0.10) - 1 = 0.10
        assert compute_metrics(self.TRADES)["total_return"] == pytest.approx(0.10, rel=1e-4)

    def test_win_rate_is_1_for_positive_return(self):
        assert compute_metrics(self.TRADES)["win_rate"] == pytest.approx(1.0)

    def test_avg_alpha_equals_trade_alpha(self):
        assert compute_metrics(self.TRADES)["avg_alpha"] == pytest.approx(0.05, rel=1e-4)

    def test_max_drawdown_is_zero_for_single_winning_trade(self):
        # Equity curve never falls below its peak with one positive trade.
        assert compute_metrics(self.TRADES)["max_drawdown"] == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Multiple trades
# ---------------------------------------------------------------------------

class TestMultipleTrades:
    # Two trades: +10% and -5%
    TRADES = _trades((0.10, 0.05), (-0.05, -0.02))

    def test_total_trades_is_2(self):
        assert compute_metrics(self.TRADES)["total_trades"] == 2

    def test_total_return_is_compounded(self):
        # (1.10 * 0.95) - 1 = 0.045
        expected = (1.10 * 0.95) - 1
        assert compute_metrics(self.TRADES)["total_return"] == pytest.approx(expected, rel=1e-4)

    def test_win_rate_is_half(self):
        assert compute_metrics(self.TRADES)["win_rate"] == pytest.approx(0.5)

    def test_avg_alpha_is_mean_of_alphas(self):
        expected = (0.05 + (-0.02)) / 2
        assert compute_metrics(self.TRADES)["avg_alpha"] == pytest.approx(expected, rel=1e-4)

    def test_max_drawdown_is_negative_after_losing_trade(self):
        # Peak after trade 1: 1.10; trough after trade 2: 1.10 * 0.95 = 1.045
        # Drawdown = (1.045 - 1.10) / 1.10 ≈ -0.05
        metrics = compute_metrics(self.TRADES)
        assert metrics["max_drawdown"] < 0


# ---------------------------------------------------------------------------
# All-losing trades
# ---------------------------------------------------------------------------

class TestAllLosingTrades:
    TRADES = _trades((-0.05, -0.03), (-0.08, -0.04))

    def test_win_rate_is_zero(self):
        assert compute_metrics(self.TRADES)["win_rate"] == pytest.approx(0.0)

    def test_total_return_is_negative(self):
        assert compute_metrics(self.TRADES)["total_return"] < 0

    def test_max_drawdown_is_negative(self):
        assert compute_metrics(self.TRADES)["max_drawdown"] < 0


# ---------------------------------------------------------------------------
# Output keys
# ---------------------------------------------------------------------------

class TestOutputKeys:
    def test_all_expected_keys_present(self):
        metrics = compute_metrics(_trades((0.05, 0.02)))
        expected = {
            "total_trades", "total_return", "ann_return",
            "sharpe", "win_rate", "avg_alpha", "max_drawdown",
        }
        assert expected == set(metrics.keys())
