"""
CLI entry point for the TradingAgents + Alpaca trading bot.

Commands:

  Backtest (historical signal replay):
    python run.py backtest --start 2025-01-01 --end 2025-06-30
    python run.py backtest --start 2025-01-01 --end 2025-06-30 --tickers NVDA AAPL MSFT

  Live paper trading (scheduler):
    python run.py live            # start scheduler (fires daily at 09:45 ET)
    python run.py live --now      # fire once immediately — useful for testing
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the same directory as this file
load_dotenv(Path(__file__).parent / ".env")


# ---------------------------------------------------------------------------
# Guard: fail fast if required env vars are missing
# ---------------------------------------------------------------------------

def _require_env(*keys: str) -> None:
    missing = [k for k in keys if not os.environ.get(k)]
    if missing:
        print(f"ERROR: missing environment variable(s): {', '.join(missing)}")
        print("Copy .env.example to .env and fill in your API keys.")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Sub-command handlers
# ---------------------------------------------------------------------------

def cmd_backtest(args: argparse.Namespace) -> None:
    _require_env("ANTHROPIC_API_KEY")

    import config
    from backtest import run_backtest
    from performance import print_report

    tickers = args.tickers or config.WATCHLIST
    print(f"Tickers  : {tickers}")
    print(f"Date range: {args.start} → {args.end}")
    print(f"Hold for : {config.HOLDING_DAYS} trading days per trade\n")

    trades = run_backtest(tickers, args.start, args.end)

    if not trades.empty:
        out_dir  = Path(config.RESULTS_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"backtest_{args.start}_{args.end}.csv"
        trades.to_csv(out_path, index=False)
        print(f"Trades saved → {out_path}")

    print_report(trades)


def cmd_live(args: argparse.Namespace) -> None:
    _require_env("ALPACA_API_KEY", "ALPACA_SECRET_KEY", "ANTHROPIC_API_KEY")

    from live_trader import run_daily, start_scheduler

    if args.now:
        print("Firing once immediately (--now mode)...\n")
        run_daily()
    else:
        start_scheduler()


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="TradingAgents + Alpaca paper trading bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- backtest ---
    bt = sub.add_parser("backtest", help="Run a historical backtest")
    bt.add_argument("--start",   required=True, metavar="YYYY-MM-DD",
                    help="Start date (inclusive)")
    bt.add_argument("--end",     required=True, metavar="YYYY-MM-DD",
                    help="End date (inclusive)")
    bt.add_argument("--tickers", nargs="+", metavar="TICKER",
                    help="Override watchlist (default: WATCHLIST in config.py)")

    # --- live ---
    lv = sub.add_parser("live", help="Start the live paper trading scheduler")
    lv.add_argument("--now", action="store_true",
                    help="Fire the daily job once immediately (for testing)")

    args = parser.parse_args()

    if args.command == "backtest":
        cmd_backtest(args)
    elif args.command == "live":
        cmd_live(args)


if __name__ == "__main__":
    main()
