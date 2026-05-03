import os

# ---------------------------------------------------------------------------
# Watchlist
# Edit this to trade whatever tickers you want.
# ---------------------------------------------------------------------------
WATCHLIST = ["NVDA", "AAPL", "MSFT", "GOOGL", "AMZN"]

# ---------------------------------------------------------------------------
# Position sizing
# Each ticker gets up to BUDGET_PER_TICKER_PCT of total portfolio value.
# The signal multiplier below scales that budget (1.0 = full, 0.5 = half).
# ---------------------------------------------------------------------------
BUDGET_PER_TICKER_PCT = 0.10  # 10% per ticker → max 50% deployed across 5

# Long-only signal → position multiplier
#   None  = no action (keep existing position or skip)
#   0.0   = close any open long
#   >0.0  = open / add to long at this fraction of the ticker budget
SIGNAL_MAP = {
    "Buy":         1.0,
    "Overweight":  0.5,
    "Hold":        None,
    "Underweight": 0.0,
    "Sell":        0.0,
}

# ---------------------------------------------------------------------------
# Risk controls
# ---------------------------------------------------------------------------
MAX_TOTAL_EXPOSURE_PCT = 0.80  # never deploy more than 80% of portfolio
DAILY_LOSS_LIMIT_PCT   = 0.05  # halt new orders if down 5% on the day

# ---------------------------------------------------------------------------
# Trade lifecycle
# ---------------------------------------------------------------------------
HOLDING_DAYS = 5  # exit after N trading days (backtest + live)

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
CACHE_DIR   = os.path.expanduser("~/.trading-bot/cache")    # LLM result cache
RESULTS_DIR = os.path.expanduser("~/.trading-bot/results")  # backtest CSVs

# ---------------------------------------------------------------------------
# Live scheduler
# ---------------------------------------------------------------------------
SCHEDULE_TIME_ET = "09:45"  # fire daily at this time (Eastern), Mon–Fri

# ---------------------------------------------------------------------------
# Alpaca
# ---------------------------------------------------------------------------
ALPACA_PAPER = True  # True = paper trading; False = live (be careful!)

# ---------------------------------------------------------------------------
# TradingAgents LLM config
# claude-opus-4-7  → deep reasoning (research manager, portfolio manager)
# claude-haiku-4-5 → quick tasks (signal extraction, formatting)
# ---------------------------------------------------------------------------
TA_LLM_PROVIDER     = "anthropic"
TA_DEEP_MODEL       = "claude-opus-4-7"
TA_QUICK_MODEL      = "claude-haiku-4-5"
TA_DEBATE_ROUNDS    = 1
TA_ANTHROPIC_EFFORT = None  # effort param unsupported by langchain-anthropic; omit it
