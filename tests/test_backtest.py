"""
Tests for backtest.py.

TradingAgentsGraph is stubbed out via sys.modules so no LLM API calls are
ever made.  Price data is supplied through a yfinance mock, and signals are
injected via the on-disk cache (the same technique documented in TESTING.md).
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Stub tradingagents before it can be imported inside run_backtest().
# The import lives inside the function body, so setting sys.modules here is
# sufficient — Python checks sys.modules before hitting the file system.
# ---------------------------------------------------------------------------
_mock_default_config_module = MagicMock()
_mock_default_config_module.DEFAULT_CONFIG = {}

sys.modules.setdefault("tradingagents", MagicMock())
sys.modules.setdefault("tradingagents.graph", MagicMock())
sys.modules.setdefault("tradingagents.graph.trading_graph", MagicMock())
sys.modules.setdefault("tradingagents.default_config", _mock_default_config_module)

# Safe to import now
sys.path.insert(0, str(Path(__file__).parent.parent))
import backtest  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _price_df(dates, opens, closes):
    """Build a minimal yfinance-style price DataFrame."""
    idx = pd.DatetimeIndex(pd.to_datetime(dates))
    return pd.DataFrame({"Open": opens, "Close": closes}, index=idx)


# Shared 7-day price series used by integration tests.
# Signal date  : 2024-01-02
# Entry        : 2024-01-03  open  = 101.0
# Exit (day +5): 2024-01-10  close = 106.5
_DATES = [
    "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05",
    "2024-01-08", "2024-01-09", "2024-01-10",
]
_MSFT = _price_df(_DATES, [100, 101, 102, 103, 104, 105, 106],
                           [100.5, 101.5, 102.5, 103.5, 104.5, 105.5, 106.5])
_SPY  = _price_df(_DATES, [400, 401, 402, 403, 404, 405, 406],
                           [400.5, 401.5, 402.5, 403.5, 404.5, 405.5, 406.5])

TRADE_DATE = "2024-01-02"
EXPECTED_ENTRY = 101.0   # 2024-01-03 open
EXPECTED_EXIT  = 106.5   # 2024-01-10 close  (entry_idx=1, exit_idx=1+5=6)


def _mock_yf_download(sym, **kwargs):
    return _MSFT.copy() if sym != "SPY" else _SPY.copy()


def _inject_cache(tmp_path, ticker, date, signal):
    cache_dir = tmp_path / ticker
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{date}.json").write_text(json.dumps({"signal": signal}))


# ---------------------------------------------------------------------------
# _flatten_columns
# ---------------------------------------------------------------------------

class TestFlattenColumns:
    def test_single_index_is_unchanged(self):
        df = _price_df(["2024-01-02"], [100.0], [101.0])
        result = backtest._flatten_columns(df)
        assert list(result.columns) == ["Open", "Close"]

    def test_multiindex_is_collapsed_to_first_level(self):
        df = _price_df(["2024-01-02"], [100.0], [101.0])
        df.columns = pd.MultiIndex.from_tuples([("Open", "MSFT"), ("Close", "MSFT")])
        result = backtest._flatten_columns(df)
        assert list(result.columns) == ["Open", "Close"]


# ---------------------------------------------------------------------------
# _next_open_after
# ---------------------------------------------------------------------------

class TestNextOpenAfter:
    PRICES = _price_df(
        ["2024-01-02", "2024-01-03", "2024-01-04"],
        [100.0, 101.0, 102.0],
        [100.5, 101.5, 102.5],
    )

    def test_returns_open_of_next_trading_day(self):
        result = backtest._next_open_after(self.PRICES, "2024-01-02")
        assert result == pytest.approx(101.0)

    def test_trade_date_itself_is_not_entry(self):
        # The entry must be *strictly after* the trade date.
        result = backtest._next_open_after(self.PRICES, "2024-01-03")
        assert result == pytest.approx(102.0)

    def test_returns_none_when_no_later_date_exists(self):
        assert backtest._next_open_after(self.PRICES, "2024-01-04") is None


# ---------------------------------------------------------------------------
# _close_n_days_later
# ---------------------------------------------------------------------------

class TestCloseNDaysLater:
    PRICES = _price_df(
        ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05",
         "2024-01-08", "2024-01-09", "2024-01-10"],
        [100, 101, 102, 103, 104, 105, 106],
        [100.5, 101.5, 102.5, 103.5, 104.5, 105.5, 106.5],
    )

    def test_n_equals_5(self):
        # entry=idx 1 (2024-01-03), exit=idx 6 (2024-01-10)
        result = backtest._close_n_days_later(self.PRICES, "2024-01-02", 5)
        assert result == pytest.approx(106.5)

    def test_n_equals_1(self):
        # entry=idx 1 (2024-01-03), exit=idx 2 (2024-01-04)
        result = backtest._close_n_days_later(self.PRICES, "2024-01-02", 1)
        assert result == pytest.approx(102.5)

    def test_returns_none_when_insufficient_data_for_exit(self):
        # Only one day after 2024-01-09, so n=5 is impossible.
        assert backtest._close_n_days_later(self.PRICES, "2024-01-09", 5) is None

    def test_returns_none_when_no_entry_day_found(self):
        assert backtest._close_n_days_later(self.PRICES, "2024-01-10", 1) is None


# ---------------------------------------------------------------------------
# run_backtest — integration tests (all signals from cache, no LLM calls)
# ---------------------------------------------------------------------------

class TestRunBacktest:

    def _run(self, tmp_path, monkeypatch, signal):
        monkeypatch.setattr(backtest.config, "CACHE_DIR", str(tmp_path))
        _inject_cache(tmp_path, "MSFT", TRADE_DATE, signal)
        with (
            patch("backtest._get_trading_days", return_value=[TRADE_DATE]),
            patch("yfinance.download", side_effect=_mock_yf_download),
        ):
            return backtest.run_backtest(["MSFT"], TRADE_DATE, TRADE_DATE)

    def test_buy_signal_produces_one_trade(self, tmp_path, monkeypatch):
        trades = self._run(tmp_path, monkeypatch, "Buy")
        assert len(trades) == 1

    def test_buy_signal_entry_price_is_next_day_open(self, tmp_path, monkeypatch):
        trades = self._run(tmp_path, monkeypatch, "Buy")
        assert trades.iloc[0]["entry_price"] == pytest.approx(EXPECTED_ENTRY, abs=0.01)

    def test_buy_signal_exit_price_is_close_after_holding_days(self, tmp_path, monkeypatch):
        trades = self._run(tmp_path, monkeypatch, "Buy")
        assert trades.iloc[0]["exit_price"] == pytest.approx(EXPECTED_EXIT, abs=0.01)

    def test_buy_signal_raw_return_calculation(self, tmp_path, monkeypatch):
        trades = self._run(tmp_path, monkeypatch, "Buy")
        expected = (EXPECTED_EXIT - EXPECTED_ENTRY) / EXPECTED_ENTRY
        assert trades.iloc[0]["raw_return"] == pytest.approx(expected, rel=1e-4)

    def test_buy_signal_alpha_subtracts_spy_return(self, tmp_path, monkeypatch):
        trades = self._run(tmp_path, monkeypatch, "Buy")
        row = trades.iloc[0]
        # SPY: entry=401.0 (2024-01-03 open), exit=406.5 (2024-01-10 close)
        spy_return = (406.5 - 401.0) / 401.0
        assert row["alpha"] == pytest.approx(row["raw_return"] - spy_return, rel=1e-4)

    def test_buy_signal_multiplier_is_1(self, tmp_path, monkeypatch):
        trades = self._run(tmp_path, monkeypatch, "Buy")
        assert trades.iloc[0]["multiplier"] == 1.0

    def test_overweight_signal_multiplier_is_half(self, tmp_path, monkeypatch):
        trades = self._run(tmp_path, monkeypatch, "Overweight")
        assert len(trades) == 1
        assert trades.iloc[0]["multiplier"] == 0.5

    def test_hold_signal_produces_no_trade(self, tmp_path, monkeypatch):
        trades = self._run(tmp_path, monkeypatch, "Hold")
        assert trades.empty

    def test_sell_signal_produces_no_trade(self, tmp_path, monkeypatch):
        trades = self._run(tmp_path, monkeypatch, "Sell")
        assert trades.empty

    def test_underweight_signal_produces_no_trade(self, tmp_path, monkeypatch):
        trades = self._run(tmp_path, monkeypatch, "Underweight")
        assert trades.empty

    def test_trade_row_contains_expected_columns(self, tmp_path, monkeypatch):
        trades = self._run(tmp_path, monkeypatch, "Buy")
        expected_cols = {
            "ticker", "date", "signal", "multiplier",
            "entry_price", "exit_price", "raw_return", "spy_return", "alpha",
        }
        assert expected_cols.issubset(set(trades.columns))
