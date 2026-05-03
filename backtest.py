"""
Historical signal replay and P&L calculation.

Each (ticker, date) propagate() result is cached to disk so you only pay
LLM API costs once per combination — re-running the backtest with the same
date range is free after the first pass.

Usage (via run.py):
    python run.py backtest --start 2025-01-01 --end 2025-06-30
    python run.py backtest --start 2025-01-01 --end 2025-06-30 --tickers NVDA AAPL
"""

import json
from pathlib import Path
from typing import List, Optional

import pandas as pd
import yfinance as yf

import config


# ---------------------------------------------------------------------------
# Disk cache helpers
# ---------------------------------------------------------------------------

def _cache_path(ticker: str, trade_date: str) -> Path:
    p = Path(config.CACHE_DIR) / ticker
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{trade_date}.json"


def _load_cache(ticker: str, trade_date: str) -> Optional[dict]:
    path = _cache_path(ticker, trade_date)
    return json.loads(path.read_text()) if path.exists() else None


def _save_cache(ticker: str, trade_date: str, data: dict) -> None:
    _cache_path(ticker, trade_date).write_text(json.dumps(data))


# ---------------------------------------------------------------------------
# Price helpers
# ---------------------------------------------------------------------------

def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse yfinance MultiIndex columns (col, ticker) → col for single-ticker downloads."""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def _get_trading_days(start: str, end: str) -> List[str]:
    """Return ISO date strings for every trading day in [start, end]."""
    spy = _flatten_columns(
        yf.download("SPY", start=start, end=end, progress=False, auto_adjust=True)
    )
    return [str(d.date()) for d in spy.index]


def _next_open_after(prices: pd.DataFrame, trade_date: str) -> Optional[float]:
    """
    Return the open price on the first trading day strictly after trade_date.
    This simulates a next-morning market-open fill (realistic for EOD signals).
    """
    dates = [str(d.date()) for d in prices.index]
    for i, d in enumerate(dates):
        if d > trade_date:
            return float(prices["Open"].iloc[i])
    return None


def _close_n_days_later(
    prices: pd.DataFrame, trade_date: str, n: int
) -> Optional[float]:
    """
    Return the close price N trading days after trade_date.
    Counts from the entry day (day after trade_date) forward n more days.
    """
    dates = [str(d.date()) for d in prices.index]
    # Find the entry day index
    entry_idx = None
    for i, d in enumerate(dates):
        if d > trade_date:
            entry_idx = i
            break
    if entry_idx is None:
        return None
    exit_idx = entry_idx + n
    if exit_idx >= len(prices):
        return None
    return float(prices["Close"].iloc[exit_idx])


# ---------------------------------------------------------------------------
# Main backtest runner
# ---------------------------------------------------------------------------

def run_backtest(
    tickers: List[str],
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """
    Run a full backtest. Returns a DataFrame with one row per entered trade.

    For each trading day and each ticker:
      - Call ta.propagate() (or load from cache)
      - Map signal to multiplier via config.SIGNAL_MAP
      - Simulate entry at next-day open, exit at close N days later
      - Compute raw return and alpha vs SPY
    """
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.default_config import DEFAULT_CONFIG

    ta_cfg = DEFAULT_CONFIG.copy()
    ta_cfg["llm_provider"]      = config.TA_LLM_PROVIDER
    ta_cfg["deep_think_llm"]    = config.TA_DEEP_MODEL
    ta_cfg["quick_think_llm"]   = config.TA_QUICK_MODEL
    ta_cfg["max_debate_rounds"] = config.TA_DEBATE_ROUNDS
    ta_cfg["anthropic_effort"]  = config.TA_ANTHROPIC_EFFORT

    trading_days = _get_trading_days(start_date, end_date)
    total_calls  = len(tickers) * len(trading_days)
    print(
        f"Backtesting {len(tickers)} ticker(s) × {len(trading_days)} trading days "
        f"= up to {total_calls} propagate() calls\n"
        f"(cached results are free — only uncached dates hit the LLM API)\n"
    )

    # Pre-download all price data once
    print("Downloading price data...")
    price_cache = {}
    for sym in tickers + ["SPY"]:
        price_cache[sym] = _flatten_columns(
            yf.download(sym, start=start_date, progress=False, auto_adjust=True)
        )
    spy_prices = price_cache["SPY"]
    print("Done.\n")

    trades = []

    for ticker in tickers:
        print(f"{'='*50}")
        print(f"  {ticker}")
        print(f"{'='*50}")
        prices = price_cache[ticker]

        # One TradingAgentsGraph instance per ticker (holds LLM + memory state)
        ta = TradingAgentsGraph(debug=False, config=ta_cfg)

        for trade_date in trading_days:
            cached = _load_cache(ticker, trade_date)
            if cached:
                signal = cached["signal"]
                print(f"  {trade_date}  {signal:<12}  (cached)")
            else:
                print(f"  {trade_date}  running...", end=" ", flush=True)
                try:
                    _, signal = ta.propagate(ticker, trade_date)
                    _save_cache(ticker, trade_date, {"signal": signal})
                    print(signal)
                except Exception as exc:
                    print(f"ERROR: {exc}")
                    continue

            # Map signal to multiplier
            multiplier = config.SIGNAL_MAP.get(signal)
            if not multiplier:  # None (Hold) or 0.0 (Sell/Underweight) → skip
                continue

            # Simulate fill prices
            entry_price = _next_open_after(prices, trade_date)
            exit_price  = _close_n_days_later(prices, trade_date, config.HOLDING_DAYS)
            if entry_price is None or exit_price is None:
                print(f"  {trade_date}  skipped (insufficient price data)")
                continue

            raw_return = (exit_price - entry_price) / entry_price

            # SPY return over the same window
            spy_entry = _next_open_after(spy_prices, trade_date)
            spy_exit  = _close_n_days_later(spy_prices, trade_date, config.HOLDING_DAYS)
            spy_return = (
                (spy_exit - spy_entry) / spy_entry
                if spy_entry and spy_exit
                else 0.0
            )

            trades.append({
                "ticker":      ticker,
                "date":        trade_date,
                "signal":      signal,
                "multiplier":  multiplier,
                "entry_price": round(entry_price, 4),
                "exit_price":  round(exit_price,  4),
                "raw_return":  raw_return,
                "spy_return":  spy_return,
                "alpha":       raw_return - spy_return,
            })

        print()

    return pd.DataFrame(trades)
