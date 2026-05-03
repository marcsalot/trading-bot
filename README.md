# trading-bot

[![Tests](https://github.com/marcsalot/trading-bot/actions/workflows/test.yml/badge.svg)](https://github.com/marcsalot/trading-bot/actions/workflows/test.yml)

A long-only equities trading bot powered by [TradingAgents](https://github.com/TauricResearch/TradingAgents) (multi-agent LLM research framework) and [Alpaca](https://alpaca.markets) (paper/live order execution).

Each trading day the bot runs a multi-agent debate to produce a directional signal (`Buy`, `Overweight`, `Hold`, `Underweight`, `Sell`) for every ticker on your watchlist. Actionable signals are translated into fractional-notional market orders on Alpaca. Positions are automatically closed after a configurable holding period.

## Features

- **Backtest** — replay signals over any historical date range; results saved to CSV with full performance metrics (total return, Sharpe, win rate, alpha vs SPY, max drawdown)
- **Live paper trading** — APScheduler-based daily job fires at a configurable time (default 09:45 ET); open positions are tracked across restarts in `~/.trading-bot/open_trades.json`
- **LLM caching** — signals are cached to disk (`~/.trading-bot/cache/`) so re-running a backtest never re-calls the LLM for dates already processed
- **Risk guards** — daily loss limit and maximum portfolio exposure checks before any order is placed

## Requirements

- Python 3.10+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip
- An [Alpaca](https://alpaca.markets) account (free paper trading)
- An Anthropic API key (or OpenAI / Google — set `TA_LLM_PROVIDER` in `config.py`)

## Setup

**1. Clone the repo and install dependencies**

```bash
git clone https://github.com/marcsalot/trading-bot.git
cd trading-bot
```

Install the TradingAgents library (not on PyPI):

```bash
git clone https://github.com/TauricResearch/TradingAgents.git ~/TradingAgents
```

Create a virtual environment with Python 3.10+ and install everything:

```bash
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -r requirements.txt -e ~/TradingAgents
```

**2. Configure API keys**

```bash
cp .env.example .env
```

Edit `.env` and fill in your keys:

```
ALPACA_API_KEY=...
ALPACA_SECRET_KEY=...
ANTHROPIC_API_KEY=...
```

**3. (Optional) Edit `config.py`**

Key settings:

| Setting | Default | Description |
|---|---|---|
| `WATCHLIST` | `["NVDA", "AAPL", "MSFT", "GOOGL", "AMZN"]` | Tickers to trade |
| `HOLDING_DAYS` | `5` | Exit after N trading days |
| `BUDGET_PER_TICKER_PCT` | `0.10` | Max portfolio fraction per ticker |
| `ALPACA_PAPER` | `True` | Set to `False` for live trading |
| `SCHEDULE_TIME_ET` | `"09:45"` | Daily job fire time (Eastern) |
| `TA_LLM_PROVIDER` | `"anthropic"` | LLM provider (`anthropic`, `openai`, `google`) |
| `TA_DEEP_MODEL` | `"claude-opus-4-7"` | Model for deep reasoning agents |
| `TA_QUICK_MODEL` | `"claude-haiku-4-5"` | Model for quick tasks |

## Usage

All commands are run via `run.py` using the venv Python:

```bash
# Backtest over a date range (default watchlist)
.venv/bin/python run.py backtest --start 2025-01-01 --end 2025-03-31

# Backtest with specific tickers
.venv/bin/python run.py backtest --start 2025-01-01 --end 2025-03-31 --tickers NVDA AAPL

# Start the live paper trading scheduler (runs indefinitely, fires daily at 09:45 ET)
.venv/bin/python run.py live

# Fire the daily job once immediately (useful for testing live mode)
.venv/bin/python run.py live --now
```

Backtest results are saved to `~/.trading-bot/results/backtest_<start>_<end>.csv`.

## Project structure

```
run.py            CLI entry point (backtest + live subcommands)
backtest.py       Historical signal replay and trade simulation
live_trader.py    Daily scheduler: signal → order → position lifecycle
broker.py         Alpaca order/position abstraction
risk.py           Pre-order risk guards (exposure, daily loss limit)
performance.py    Metrics: return, Sharpe, win rate, alpha, drawdown
config.py         All user-configurable settings
.env.example      API key template
TESTING.md        Cache-injection testing procedure
```

## Testing

The test suite runs automatically on every push and pull request via GitHub Actions (Python 3.13, ubuntu-latest). No API keys are required — `TradingAgentsGraph` is stubbed and `yfinance` is mocked.

**Run locally:**

```bash
.venv/bin/pytest tests/ -v
```

**Test coverage:**

| File | Tests | What's covered |
|---|---|---|
| `tests/test_backtest.py` | 22 | `_flatten_columns`, `_next_open_after`, `_close_n_days_later`; `run_backtest` integration for all 5 signal types with verified entry/exit prices, returns, and alpha |
| `tests/test_performance.py` | 13 | `compute_metrics` — compounding, win rate, alpha, drawdown, empty input, output keys |

**Manual testing — cache injection:**

For ad-hoc verification of any signal or date without hitting the LLM, inject a signal directly into the cache and run the backtest for that date. See [TESTING.md](TESTING.md) for the full procedure and a worked example.

**Live mode testing:**

```bash
.venv/bin/python run.py live --now
```

Fires the daily job once immediately against your Alpaca paper account.
