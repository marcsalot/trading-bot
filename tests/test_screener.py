"""
Tests for screener.py — screen_universe() and _score_candidates().

yfinance and _get_most_actives are mocked throughout so no network
calls are made.
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import screener  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_raw(tickers, closes, volumes, days=25):
    """
    Build a yfinance-style MultiIndex DataFrame for multiple tickers.

    Columns: MultiIndex (price_col, ticker)
    Each ticker gets `days` rows ending on 2024-01-31.
    """
    import numpy as np

    dates = pd.date_range("2024-01-01", periods=days, freq="B")
    arrays = []
    for sym, close_val, vol_val in zip(tickers, closes, volumes):
        close_series = pd.Series([close_val] * days, index=dates, name=("Close", sym))
        vol_series   = pd.Series([vol_val]   * days, index=dates, name=("Volume", sym))
        arrays.append((sym, close_val, vol_val, close_series, vol_series))

    close_df  = pd.concat([a[3] for a in arrays], axis=1)
    volume_df = pd.concat([a[4] for a in arrays], axis=1)

    close_df.columns  = pd.MultiIndex.from_tuples([("Close",  sym) for sym in tickers])
    volume_df.columns = pd.MultiIndex.from_tuples([("Volume", sym) for sym in tickers])

    return pd.concat([close_df, volume_df], axis=1)


def _make_raw_single(close_val, vol_val, days=25):
    """Build a flat (non-MultiIndex) DataFrame for a single ticker."""
    dates = pd.date_range("2024-01-01", periods=days, freq="B")
    return pd.DataFrame(
        {"Close": [close_val] * days, "Volume": [vol_val] * days},
        index=dates,
    )


# ---------------------------------------------------------------------------
# _score_candidates
# ---------------------------------------------------------------------------

class TestScoreCandidates:

    def test_above_sma_passes_filter(self, monkeypatch):
        # Days 1-24 = 100, day 25 = 120 → close(120) > sma20(≈101) → passes
        monkeypatch.setattr(screener.config, "SCREENER_MIN_PRICE", 10.0)
        monkeypatch.setattr(screener.config, "SCREENER_MIN_AVG_VOLUME", 500_000)

        dates = pd.date_range("2024-01-01", periods=25, freq="B")
        close_col = pd.Series([100.0] * 24 + [120.0], index=dates, name=("Close",  "AAPL"))
        vol_col   = pd.Series([1_000_000] * 25,       index=dates, name=("Volume", "AAPL"))
        raw = pd.concat([close_col.to_frame(), vol_col.to_frame()], axis=1)
        raw.columns = pd.MultiIndex.from_tuples([("Close", "AAPL"), ("Volume", "AAPL")])

        with patch("yfinance.download", return_value=raw):
            result = screener._score_candidates(["AAPL"])

        assert len(result) == 1
        assert result.iloc[0]["ticker"] == "AAPL"

    def test_below_sma_excluded(self, monkeypatch):
        # All days same price → close == sma20 → fails (close must be > sma20)
        monkeypatch.setattr(screener.config, "SCREENER_MIN_PRICE", 10.0)
        monkeypatch.setattr(screener.config, "SCREENER_MIN_AVG_VOLUME", 500_000)

        raw = _make_raw(["AAPL"], [100.0], [1_000_000])
        with patch("yfinance.download", return_value=raw):
            result = screener._score_candidates(["AAPL"])

        assert result.empty

    def test_below_min_price_excluded(self, monkeypatch):
        # Price floor = 50; series 20..44 has last close 44 > sma20≈32 (passes SMA)
        # but 44 < floor 50 → excluded
        monkeypatch.setattr(screener.config, "SCREENER_MIN_PRICE", 50.0)
        monkeypatch.setattr(screener.config, "SCREENER_MIN_AVG_VOLUME", 500_000)

        dates = pd.date_range("2024-01-01", periods=25, freq="B")
        close_col = pd.Series(range(20, 45), index=dates, name=("Close",  "AAPL"))
        vol_col   = pd.Series([1_000_000] * 25, index=dates, name=("Volume", "AAPL"))
        raw = pd.concat([close_col.to_frame(), vol_col.to_frame()], axis=1)
        raw.columns = pd.MultiIndex.from_tuples([("Close", "AAPL"), ("Volume", "AAPL")])

        with patch("yfinance.download", return_value=raw):
            result = screener._score_candidates(["AAPL"])

        assert result.empty

    def test_below_min_volume_excluded(self, monkeypatch):
        monkeypatch.setattr(screener.config, "SCREENER_MIN_PRICE", 10.0)
        monkeypatch.setattr(screener.config, "SCREENER_MIN_AVG_VOLUME", 5_000_000)

        # avg_vol = 1_000_000 < min 5_000_000
        dates = pd.date_range("2024-01-01", periods=25, freq="B")
        closes  = list(range(100, 125))   # rising → last > sma20
        volumes = [1_000_000] * 25
        close_col  = pd.Series(closes,  index=dates, name=("Close",  "AAPL"))
        vol_col    = pd.Series(volumes, index=dates, name=("Volume", "AAPL"))
        raw = pd.concat([close_col.to_frame(), vol_col.to_frame()], axis=1)
        raw.columns = pd.MultiIndex.from_tuples([("Close", "AAPL"), ("Volume", "AAPL")])

        with patch("yfinance.download", return_value=raw):
            result = screener._score_candidates(["AAPL"])

        assert result.empty

    def test_sorted_by_score_descending(self, monkeypatch):
        monkeypatch.setattr(screener.config, "SCREENER_MIN_PRICE", 10.0)
        monkeypatch.setattr(screener.config, "SCREENER_MIN_AVG_VOLUME", 500_000)

        # MSFT: close=120, sma20=100 → sma_ratio=1.20 (higher score)
        # AAPL: close=105, sma20=100 → sma_ratio=1.05 (lower score)
        # Both have same volume so vol_ratio=1.0
        dates = pd.date_range("2024-01-01", periods=25, freq="B")

        def _series(vals, sym, col):
            return pd.Series(vals, index=dates, name=(col, sym))

        msft_close  = _series([100] * 24 + [120], "MSFT", "Close")
        msft_vol    = _series([1_000_000] * 25,   "MSFT", "Volume")
        aapl_close  = _series([100] * 24 + [105], "AAPL", "Close")
        aapl_vol    = _series([1_000_000] * 25,   "AAPL", "Volume")

        raw = pd.concat(
            [msft_close.to_frame(), msft_vol.to_frame(),
             aapl_close.to_frame(), aapl_vol.to_frame()],
            axis=1,
        )
        raw.columns = pd.MultiIndex.from_tuples([
            ("Close", "MSFT"), ("Volume", "MSFT"),
            ("Close", "AAPL"), ("Volume", "AAPL"),
        ])

        with patch("yfinance.download", return_value=raw):
            result = screener._score_candidates(["MSFT", "AAPL"])

        assert list(result["ticker"]) == ["MSFT", "AAPL"]
        assert result.iloc[0]["score"] > result.iloc[1]["score"]

    def test_empty_on_empty_input(self):
        result = screener._score_candidates([])
        assert result.empty

    def test_empty_on_empty_download(self):
        with patch("yfinance.download", return_value=pd.DataFrame()):
            result = screener._score_candidates(["AAPL"])
        assert result.empty


# ---------------------------------------------------------------------------
# screen_universe
# ---------------------------------------------------------------------------

class TestScreenUniverse:

    def _passing_raw(self, tickers):
        """Raw data where all tickers pass filters (rising close, high volume)."""
        dates = pd.date_range("2024-01-01", periods=25, freq="B")
        frames = []
        for sym in tickers:
            closes  = list(range(100, 125))   # rising → last(124) > sma20≈112
            volumes = [2_000_000] * 25
            frames.append(pd.Series(closes,  index=dates, name=("Close",  sym)))
            frames.append(pd.Series(volumes, index=dates, name=("Volume", sym)))
        raw = pd.concat(frames, axis=1)
        raw.columns = pd.MultiIndex.from_tuples(raw.columns.tolist())
        return raw

    def test_returns_list_of_strings(self, monkeypatch):
        monkeypatch.setattr(screener.config, "SCREENER_MIN_PRICE", 10.0)
        monkeypatch.setattr(screener.config, "SCREENER_MIN_AVG_VOLUME", 500_000)
        monkeypatch.setattr(screener.config, "SCREENER_WATCHLIST_SIZE", 3)
        monkeypatch.setattr(screener.config, "SCREENER_UNIVERSE_SIZE", 5)

        candidates = ["AAPL", "MSFT", "NVDA", "GOOGL", "META"]
        raw = self._passing_raw(candidates)
        with (
            patch("screener._get_most_actives", return_value=candidates),
            patch("yfinance.download", return_value=raw),
        ):
            result = screener.screen_universe()

        assert isinstance(result, list)
        assert all(isinstance(t, str) for t in result)

    def test_respects_watchlist_size_limit(self, monkeypatch):
        monkeypatch.setattr(screener.config, "SCREENER_MIN_PRICE", 10.0)
        monkeypatch.setattr(screener.config, "SCREENER_MIN_AVG_VOLUME", 500_000)
        monkeypatch.setattr(screener.config, "SCREENER_WATCHLIST_SIZE", 2)
        monkeypatch.setattr(screener.config, "SCREENER_UNIVERSE_SIZE", 5)

        candidates = ["AAPL", "MSFT", "NVDA", "GOOGL", "META"]
        raw = self._passing_raw(candidates)
        with (
            patch("screener._get_most_actives", return_value=candidates),
            patch("yfinance.download", return_value=raw),
        ):
            result = screener.screen_universe()

        assert len(result) <= 2

    def test_open_tickers_excluded_from_result(self, monkeypatch):
        monkeypatch.setattr(screener.config, "SCREENER_MIN_PRICE", 10.0)
        monkeypatch.setattr(screener.config, "SCREENER_MIN_AVG_VOLUME", 500_000)
        monkeypatch.setattr(screener.config, "SCREENER_WATCHLIST_SIZE", 5)
        monkeypatch.setattr(screener.config, "SCREENER_UNIVERSE_SIZE", 5)

        candidates = ["AAPL", "MSFT", "NVDA"]
        raw = self._passing_raw(candidates)
        with (
            patch("screener._get_most_actives", return_value=candidates),
            patch("yfinance.download", return_value=raw),
        ):
            result = screener.screen_universe(open_tickers={"AAPL"})

        assert "AAPL" not in result

    def test_falls_back_to_curated_universe_on_alpaca_error(self, monkeypatch):
        monkeypatch.setattr(screener.config, "SCREENER_MIN_PRICE", 10.0)
        monkeypatch.setattr(screener.config, "SCREENER_MIN_AVG_VOLUME", 500_000)
        monkeypatch.setattr(screener.config, "SCREENER_WATCHLIST_SIZE", 3)
        monkeypatch.setattr(screener.config, "SCREENER_UNIVERSE_SIZE", 5)

        fallback = ["AAPL", "MSFT", "NVDA"]
        raw = self._passing_raw(fallback)
        with (
            patch("screener._get_most_actives", side_effect=RuntimeError("API down")),
            patch("screener._get_fallback_universe", return_value=fallback),
            patch("yfinance.download", return_value=raw),
        ):
            result = screener.screen_universe()

        assert isinstance(result, list)
        assert len(result) > 0

    def test_returns_empty_list_when_no_candidates_pass_filters(self, monkeypatch):
        monkeypatch.setattr(screener.config, "SCREENER_MIN_PRICE", 10.0)
        monkeypatch.setattr(screener.config, "SCREENER_MIN_AVG_VOLUME", 500_000)
        monkeypatch.setattr(screener.config, "SCREENER_WATCHLIST_SIZE", 3)
        monkeypatch.setattr(screener.config, "SCREENER_UNIVERSE_SIZE", 3)

        with (
            patch("screener._get_most_actives", return_value=["AAPL"]),
            patch("yfinance.download", return_value=pd.DataFrame()),
        ):
            result = screener.screen_universe()

        assert result == []

    def test_returns_empty_list_when_all_candidates_are_open(self, monkeypatch):
        monkeypatch.setattr(screener.config, "SCREENER_UNIVERSE_SIZE", 3)

        with patch("screener._get_most_actives", return_value=["AAPL", "MSFT"]):
            result = screener.screen_universe(open_tickers={"AAPL", "MSFT"})

        assert result == []
