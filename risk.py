"""Position sizing and pre-trade safety guards."""

from typing import Tuple

import config
from broker import AlpacaBroker


def calculate_notional(multiplier: float, portfolio_value: float) -> float:
    """
    Compute the dollar amount to deploy for a given signal multiplier.

    Example: portfolio=$100k, BUDGET_PER_TICKER_PCT=10%, multiplier=0.5
             → notional = $100k * 0.10 * 0.5 = $5,000
    """
    return portfolio_value * config.BUDGET_PER_TICKER_PCT * multiplier


def check_guards(ticker: str, broker: AlpacaBroker) -> Tuple[bool, str]:
    """
    Run all pre-trade safety checks before submitting a buy order.
    Returns (ok, reason) — if ok is False, reason explains why.

    Guards (in order):
      1. Market must be open
      2. Daily loss limit not breached
      3. Total exposure below maximum
    """
    # 1. Market hours
    if not broker.is_market_open():
        return False, "market is closed"

    # 2. Daily loss limit
    portfolio_value = broker.get_portfolio_value()
    last_equity     = broker.get_last_equity()
    if last_equity > 0:
        daily_change = (portfolio_value - last_equity) / last_equity
        if daily_change < -config.DAILY_LOSS_LIMIT_PCT:
            return False, (
                f"daily loss limit hit "
                f"({daily_change:+.1%} vs -{config.DAILY_LOSS_LIMIT_PCT:.0%} limit)"
            )

    # 3. Max total exposure
    if portfolio_value > 0:
        exposure = broker.total_market_value() / portfolio_value
        if exposure >= config.MAX_TOTAL_EXPOSURE_PCT:
            return False, (
                f"max exposure reached "
                f"({exposure:.1%} >= {config.MAX_TOTAL_EXPOSURE_PCT:.0%})"
            )

    return True, ""
