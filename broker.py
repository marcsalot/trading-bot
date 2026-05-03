"""Thin wrapper around the Alpaca trading API."""

import os
from datetime import datetime, timezone
from typing import Optional

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus

import config


class AlpacaBroker:
    def __init__(self):
        api_key = os.environ["ALPACA_API_KEY"]
        secret  = os.environ["ALPACA_SECRET_KEY"]
        self.client = TradingClient(api_key, secret, paper=config.ALPACA_PAPER)

    # -------------------------------------------------------------------------
    # Account
    # -------------------------------------------------------------------------

    def get_portfolio_value(self) -> float:
        return float(self.client.get_account().portfolio_value)

    def get_last_equity(self) -> float:
        """Yesterday's closing equity — used to calculate daily P&L."""
        return float(self.client.get_account().last_equity)

    def is_market_open(self) -> bool:
        return self.client.get_clock().is_open

    # -------------------------------------------------------------------------
    # Positions
    # -------------------------------------------------------------------------

    def get_position(self, ticker: str) -> Optional[dict]:
        """Return current position info, or None if no position exists."""
        try:
            pos = self.client.get_open_position(ticker)
            return {
                "qty":          float(pos.qty),
                "market_value": float(pos.market_value),
                "avg_entry":    float(pos.avg_entry_price),
                "unrealized_pl": float(pos.unrealized_pl),
            }
        except Exception:
            return None

    def get_all_positions(self) -> list:
        return self.client.get_all_positions()

    def total_market_value(self) -> float:
        """Total dollar value of all open positions."""
        return sum(float(p.market_value) for p in self.get_all_positions())

    # -------------------------------------------------------------------------
    # Orders
    # -------------------------------------------------------------------------

    def buy(self, ticker: str, notional: float) -> str:
        """
        Submit a market buy order for a dollar notional amount.
        Alpaca converts the notional to shares automatically.
        Returns the order ID.
        """
        order = self.client.submit_order(MarketOrderRequest(
            symbol=ticker,
            notional=round(notional, 2),
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        ))
        return str(order.id)

    def close_position(self, ticker: str) -> Optional[str]:
        """
        Close an existing long position entirely.
        Returns the order ID, or None if there was no position to close.
        """
        if self.get_position(ticker) is None:
            return None
        order = self.client.close_position(ticker)
        return str(order.id)

    def get_filled_orders(self, ticker: str, after: datetime) -> list:
        """Return all filled orders for a ticker since the given UTC datetime."""
        return self.client.get_orders(GetOrdersRequest(
            status=QueryOrderStatus.FILLED,
            symbols=[ticker],
            after=after.replace(tzinfo=timezone.utc),
        ))
