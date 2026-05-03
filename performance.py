"""
Compute and display performance metrics from a backtest trade DataFrame.

Metrics reported:
  - Total return (compounded across all trades)
  - Annualised return
  - Sharpe ratio (annualised, rf=0)
  - Win rate
  - Average alpha vs SPY
  - Maximum drawdown
  - Per-ticker breakdown
"""

import numpy as np
import pandas as pd


def compute_metrics(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {}

    returns = trades["raw_return"].values
    n       = len(returns)

    # Compounded total return
    total_return = float((1 + pd.Series(returns)).prod() - 1)

    # Annualised return — assume ~252 trading days/year, 5-day hold per trade
    # n trades × 5 days each = total trading days covered
    trading_days_covered = n * 5
    ann_factor = 252 / max(trading_days_covered, 1)
    ann_return = float((1 + total_return) ** ann_factor - 1)

    # Sharpe ratio (annualised, rf = 0, 5-day return period)
    sharpe = float(
        (returns.mean() / (returns.std(ddof=1) + 1e-9)) * np.sqrt(252 / 5)
    )

    win_rate  = float((returns > 0).mean())
    avg_alpha = float(trades["alpha"].mean())

    # Maximum drawdown on the cumulative return equity curve
    cum      = (1 + pd.Series(returns)).cumprod()
    peak     = cum.cummax()
    drawdown = (cum - peak) / peak
    max_drawdown = float(drawdown.min())

    return {
        "total_trades":  n,
        "total_return":  total_return,
        "ann_return":    ann_return,
        "sharpe":        sharpe,
        "win_rate":      win_rate,
        "avg_alpha":     avg_alpha,
        "max_drawdown":  max_drawdown,
    }


def print_report(trades: pd.DataFrame) -> None:
    metrics = compute_metrics(trades)
    if not metrics:
        print("No trades to report.")
        return

    w = 47
    print()
    print("=" * w)
    print("  BACKTEST PERFORMANCE REPORT")
    print("=" * w)
    print(f"  Total trades       : {metrics['total_trades']}")
    print(f"  Total return       : {metrics['total_return']:>+8.2%}")
    print(f"  Annualised return  : {metrics['ann_return']:>+8.2%}")
    print(f"  Sharpe ratio       : {metrics['sharpe']:>8.2f}")
    print(f"  Win rate           : {metrics['win_rate']:>8.1%}")
    print(f"  Avg alpha vs SPY   : {metrics['avg_alpha']:>+8.2%}")
    print(f"  Max drawdown       : {metrics['max_drawdown']:>8.2%}")
    print("=" * w)

    print("\nPer-ticker breakdown:")
    print(f"  {'Ticker':<8}  {'Trades':>6}  {'Avg Ret':>8}  {'Win%':>6}  {'Avg Alpha':>10}")
    print(f"  {'-'*8}  {'-'*6}  {'-'*8}  {'-'*6}  {'-'*10}")

    per = (
        trades.groupby("ticker")
        .agg(
            trades    =("raw_return", "count"),
            avg_return=("raw_return", "mean"),
            win_rate  =("raw_return", lambda x: (x > 0).mean()),
            avg_alpha =("alpha",      "mean"),
        )
        .reset_index()
        .sort_values("avg_return", ascending=False)
    )

    for _, row in per.iterrows():
        print(
            f"  {row['ticker']:<8}  {int(row['trades']):>6}  "
            f"{row['avg_return']:>+7.2%}  {row['win_rate']:>5.0%}  "
            f"{row['avg_alpha']:>+9.2%}"
        )
    print()
