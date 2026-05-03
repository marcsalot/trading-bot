"""
Daily live paper trading scheduler.

Fires at SCHEDULE_TIME_ET every weekday (Mon–Fri):
  1. Close positions that have hit their HOLDING_DAYS limit
  2. Check current signal on all watchlist tickers
  3. Close any open longs that now have a Sell/Underweight signal
  4. Open new longs for Buy/Overweight signals (subject to risk guards)

State is persisted in ~/.trading-bot/open_trades.json so the scheduler
survives restarts without losing track of open positions.

Usage (via run.py):
    python run.py live           # start the scheduler (runs indefinitely)
    python run.py live --now     # fire once immediately (for testing)
"""

import json
import os
from datetime import date, timedelta
from datetime import datetime
from pathlib import Path
from typing import Dict

import config
from broker import AlpacaBroker
from risk import calculate_notional, check_guards

TRADES_LOG = Path(os.path.expanduser("~/.trading-bot/open_trades.json"))

# Signals that mean "exit the position"
CLOSE_SIGNALS = {"Sell", "Underweight"}


# ---------------------------------------------------------------------------
# Open-trades persistence
# ---------------------------------------------------------------------------

def _load_open_trades() -> Dict:
    if TRADES_LOG.exists():
        return json.loads(TRADES_LOG.read_text())
    return {}


def _save_open_trades(trades: Dict) -> None:
    TRADES_LOG.parent.mkdir(parents=True, exist_ok=True)
    TRADES_LOG.write_text(json.dumps(trades, indent=2))


# ---------------------------------------------------------------------------
# Holding-period helper
# ---------------------------------------------------------------------------

def _trading_days_held(open_date_str: str) -> int:
    """Approximate trading days elapsed since open_date (counts weekdays only)."""
    open_d  = date.fromisoformat(open_date_str)
    today   = date.today()
    count   = 0
    current = open_d
    while current < today:
        if current.weekday() < 5:  # Mon–Fri
            count += 1
        current += timedelta(days=1)
    return count


# ---------------------------------------------------------------------------
# Main daily job
# ---------------------------------------------------------------------------

def run_daily() -> None:
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.default_config import DEFAULT_CONFIG

    print(f"\n{'='*52}")
    print(f"  Daily run  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ET")
    print(f"{'='*52}")

    broker = AlpacaBroker()

    if not broker.is_market_open():
        print("Market is closed — skipping run.")
        return

    ta_cfg = DEFAULT_CONFIG.copy()
    ta_cfg["llm_provider"]      = config.TA_LLM_PROVIDER
    ta_cfg["deep_think_llm"]    = config.TA_DEEP_MODEL
    ta_cfg["quick_think_llm"]   = config.TA_QUICK_MODEL
    ta_cfg["max_debate_rounds"] = config.TA_DEBATE_ROUNDS
    ta_cfg["anthropic_effort"]  = config.TA_ANTHROPIC_EFFORT

    ta          = TradingAgentsGraph(debug=False, config=ta_cfg)
    open_trades = _load_open_trades()
    today_str   = str(date.today())

    # ---- Determine today's watchlist ---------------------------------------
    if config.WATCHLIST_MODE == "dynamic":
        from screener import screen_universe
        print("\n[Screener] Building dynamic watchlist...")
        screened = screen_universe(open_tickers=set(open_trades.keys()))
        if screened:
            print(f"  Selected: {screened}")
        else:
            print("  No candidates passed filters — falling back to static WATCHLIST")
        # Always include open positions so we can act on Sell/Underweight signals
        watchlist = screened or config.WATCHLIST
        watchlist = list(dict.fromkeys(watchlist + list(open_trades.keys())))
    else:
        watchlist = config.WATCHLIST

    # ---- 1. Close positions past their holding period ----------------------
    print("\n[Step 1] Checking holding periods...")
    for ticker, info in list(open_trades.items()):
        days_held = _trading_days_held(info["open_date"])
        if days_held >= config.HOLDING_DAYS:
            print(f"  {ticker}: held {days_held} trading days → closing")
            order_id = broker.close_position(ticker)
            if order_id:
                print(f"  {ticker}: close order submitted (id={order_id})")
            del open_trades[ticker]
        else:
            remaining = config.HOLDING_DAYS - days_held
            print(f"  {ticker}: {days_held} days held, {remaining} remaining")

    _save_open_trades(open_trades)

    # ---- 2. Generate signals and act ---------------------------------------
    print("\n[Step 2] Generating signals...")
    for ticker in watchlist:
        print(f"\n  {ticker}: calling propagate()...")
        try:
            _, signal = ta.propagate(ticker, today_str)
        except Exception as exc:
            print(f"  {ticker}: propagate() failed — {exc}")
            continue

        multiplier = config.SIGNAL_MAP.get(signal)
        print(f"  {ticker}: signal={signal}  multiplier={multiplier}")

        # ---- Close on Sell / Underweight -----------------------------------
        if multiplier == 0.0:
            if ticker in open_trades:
                print(f"  {ticker}: closing on {signal} signal")
                order_id = broker.close_position(ticker)
                if order_id:
                    print(f"  {ticker}: close order submitted (id={order_id})")
                del open_trades[ticker]
                _save_open_trades(open_trades)
            else:
                print(f"  {ticker}: {signal} signal but no open position — nothing to do")
            continue

        # ---- Skip Hold or already-held ticker ------------------------------
        if multiplier is None:
            print(f"  {ticker}: Hold — no action")
            continue

        if ticker in open_trades:
            print(f"  {ticker}: already open (since {open_trades[ticker]['open_date']}) — skipping")
            continue

        # ---- Risk guards before opening ------------------------------------
        ok, reason = check_guards(ticker, broker)
        if not ok:
            print(f"  {ticker}: blocked by guard — {reason}")
            continue

        # ---- Submit buy order ----------------------------------------------
        portfolio_value = broker.get_portfolio_value()
        notional        = calculate_notional(multiplier, portfolio_value)
        print(f"  {ticker}: buying ${notional:,.2f} notional")

        try:
            order_id = broker.buy(ticker, notional)
            print(f"  {ticker}: buy order submitted (id={order_id})")
            open_trades[ticker] = {
                "open_date": today_str,
                "signal":    signal,
                "order_id":  order_id,
                "notional":  notional,
            }
            _save_open_trades(open_trades)
        except Exception as exc:
            print(f"  {ticker}: order failed — {exc}")

    print(f"\nDone. Open positions: {list(open_trades.keys()) or 'none'}\n")


# ---------------------------------------------------------------------------
# Scheduler entry point
# ---------------------------------------------------------------------------

def start_scheduler() -> None:
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    hour, minute = config.SCHEDULE_TIME_ET.split(":")
    scheduler = BlockingScheduler(timezone="America/New_York")
    scheduler.add_job(
        run_daily,
        CronTrigger(
            day_of_week="mon-fri",
            hour=int(hour),
            minute=int(minute),
        ),
    )
    mode = "PAPER" if config.ALPACA_PAPER else "LIVE"
    print(f"Scheduler started [{mode}] — firing daily at {config.SCHEDULE_TIME_ET} ET (Mon–Fri)")
    print("Press Ctrl+C to stop.\n")
    scheduler.start()
