"""
Dynamic watchlist screener.

Builds a fresh watchlist each day by:
  1. Fetching the top SCREENER_UNIVERSE_SIZE most-active US equities from Alpaca
     (falls back to a curated large-cap universe if the API is unavailable)
  2. Excluding tickers already held in open positions
  3. Applying technical filters via yfinance (price > 20-day SMA, min volume,
     min price)
  4. Scoring survivors by momentum × volume-spike and returning the top
     SCREENER_WATCHLIST_SIZE tickers

Usage:
    from screener import screen_universe
    tickers = screen_universe(open_tickers={"NVDA", "AAPL"})
    # → e.g. ["MSFT", "META", "AVGO", "AMD", "TSLA"]
"""

import logging
import os
from typing import List, Set

import pandas as pd
import yfinance as yf

import config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Candidate universe
# ---------------------------------------------------------------------------

def _get_most_actives(n: int) -> List[str]:
    """Fetch the top-n most active US equities by volume from Alpaca."""
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import MostActivesRequest

    client = StockHistoricalDataClient(
        api_key=os.environ["ALPACA_API_KEY"],
        secret_key=os.environ["ALPACA_SECRET_KEY"],
    )
    result = client.get_stock_most_actives(MostActivesRequest(top=n, by="volume"))
    return [s.symbol for s in result.most_actives]


def _get_fallback_universe() -> List[str]:
    """
    Curated universe of ~100 liquid US large-caps used when the Alpaca
    screener API is unavailable (e.g. outside market hours or missing key).
    Skewed toward names with rich news/analyst coverage for better LLM signals.
    """
    return [
        # Mega-cap tech
        "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AVGO", "ORCL",
        # Semiconductors
        "AMD", "INTC", "QCOM", "MU", "AMAT", "KLAC", "LRCX", "MRVL", "TXN",
        # Software / cloud
        "CRM", "NOW", "ADBE", "INTU", "SNOW", "PANW", "FTNT", "WDAY", "ZS",
        # Financials
        "JPM", "BAC", "WFC", "GS", "MS", "BLK", "SPGI", "AXP", "V", "MA",
        # Healthcare
        "UNH", "JNJ", "LLY", "ABBV", "MRK", "AMGN", "GILD", "VRTX", "REGN",
        # Consumer
        "COST", "WMT", "HD", "TGT", "NKE", "SBUX", "MCD", "TJX", "LOW",
        # Energy / industrials
        "XOM", "CVX", "CAT", "DE", "HON", "RTX", "GE", "UNP", "BA",
        # Telecom / media
        "NFLX", "DIS", "CMCSA", "T", "VZ",
        # Other large-caps
        "PG", "KO", "PEP", "PM", "MO", "TMO", "DHR", "ABT", "MDT", "ZTS",
    ]


# ---------------------------------------------------------------------------
# Technical scoring
# ---------------------------------------------------------------------------

def _score_candidates(tickers: List[str]) -> pd.DataFrame:
    """
    Download 30 days of price/volume history for all candidates in one batch
    and compute per-ticker metrics.

    Hard filters (ticker excluded if any fail):
      - close >= SCREENER_MIN_PRICE
      - 20-day avg volume >= SCREENER_MIN_AVG_VOLUME
      - close > 20-day SMA  (price must be in an uptrend)

    Score (higher = better):
      sma_ratio  = close / sma20          (momentum strength)
      vol_ratio  = today_volume / avg_vol  (recent institutional interest)
      score      = sma_ratio * vol_ratio

    Returns a DataFrame sorted by score descending, or an empty DataFrame if
    no candidates survive the filters.
    """
    if not tickers:
        return pd.DataFrame()

    raw = yf.download(
        tickers,
        period="30d",
        progress=False,
        auto_adjust=True,
    )
    if raw.empty:
        return pd.DataFrame()

    # Normalise to (price_col → DataFrame with ticker columns).
    # yfinance returns MultiIndex (price_col, ticker) for multi-ticker
    # downloads, and a flat index for single-ticker downloads.
    multi = isinstance(raw.columns, pd.MultiIndex)

    rows = []
    for sym in tickers:
        try:
            if multi:
                close_s = raw["Close"][sym].dropna()
                vol_s   = raw["Volume"][sym].dropna()
            else:
                close_s = raw["Close"].dropna()
                vol_s   = raw["Volume"].dropna()

            if len(close_s) < 21:
                continue

            close   = float(close_s.iloc[-1])
            sma20   = float(close_s.tail(20).mean())
            volume  = float(vol_s.iloc[-1])
            avg_vol = float(vol_s.tail(20).mean())

            # Hard filters
            if close < config.SCREENER_MIN_PRICE:
                continue
            if avg_vol < config.SCREENER_MIN_AVG_VOLUME:
                continue
            if close <= sma20:
                continue

            sma_ratio = close / sma20
            vol_ratio = (volume / avg_vol) if avg_vol > 0 else 1.0

            rows.append({
                "ticker":    sym,
                "close":     round(close, 2),
                "sma20":     round(sma20, 2),
                "sma_ratio": round(sma_ratio, 4),
                "vol_ratio": round(vol_ratio, 4),
                "score":     round(sma_ratio * vol_ratio, 4),
            })
        except Exception as exc:
            logger.debug("Skipping %s: %s", sym, exc)

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).sort_values("score", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def screen_universe(open_tickers: Set[str] = None) -> List[str]:
    """
    Return up to config.SCREENER_WATCHLIST_SIZE tickers for today's session.

    Args:
        open_tickers: Symbols with existing open positions.  These are
                      excluded from the output so the bot doesn't try to
                      double-open them (existing positions are handled
                      separately in live_trader.py).

    Returns:
        List of ticker symbols, best candidates first.  May be shorter than
        SCREENER_WATCHLIST_SIZE (or empty) if few candidates pass filters.
    """
    open_tickers = open_tickers or set()

    # 1. Fetch candidate pool
    try:
        candidates = _get_most_actives(config.SCREENER_UNIVERSE_SIZE)
        logger.info("Screener: fetched %d most-actives from Alpaca", len(candidates))
    except Exception as exc:
        logger.warning(
            "Screener: Alpaca most-actives unavailable (%s) — using fallback universe",
            exc,
        )
        candidates = _get_fallback_universe()

    # 2. Exclude already-held tickers
    candidates = [t for t in candidates if t not in open_tickers]
    if not candidates:
        logger.warning("Screener: all candidates are already held — returning empty list")
        return []

    # 3. Score and filter
    scored = _score_candidates(candidates)
    if scored.empty:
        logger.warning("Screener: no candidates passed technical filters")
        return []

    picks = scored["ticker"].head(config.SCREENER_WATCHLIST_SIZE).tolist()

    logger.info(
        "Screener results (top %d of %d filtered):",
        len(picks), len(scored),
    )
    for _, row in scored.head(config.SCREENER_WATCHLIST_SIZE).iterrows():
        logger.info(
            "  %-6s  close=%.2f  sma20=%.2f  sma_ratio=%.4f  "
            "vol_ratio=%.2f  score=%.4f",
            row["ticker"], row["close"], row["sma20"],
            row["sma_ratio"], row["vol_ratio"], row["score"],
        )

    return picks
