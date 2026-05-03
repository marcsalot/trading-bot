# Testing

## Cache-injection testing

The backtest uses a disk cache at `~/.trading-bot/cache/<TICKER>/<DATE>.json`
to avoid re-calling the LLM for dates already processed.  You can exploit this
to test specific backtest scenarios without spending API credits: write any
signal directly to a cache file, run the backtest for that date, then verify
the output.

### Procedure

**1. Write a signal to the cache**

```bash
mkdir -p ~/.trading-bot/cache/<TICKER>
echo '{"signal": "<SIGNAL>"}' > ~/.trading-bot/cache/<TICKER>/<DATE>.json
```

Valid signals (defined in `config.py::SIGNAL_MAP`):

| Signal      | Multiplier | Effect                     |
|-------------|------------|----------------------------|
| `Buy`       | 1.0        | Open full position          |
| `Overweight`| 0.5        | Open half position          |
| `Hold`      | None       | No action (skipped)         |
| `Underweight`| 0.0       | Close any open long (skipped in backtest) |
| `Sell`      | 0.0        | Close any open long (skipped in backtest) |

Only `Buy` and `Overweight` produce rows in the backtest output.

**2. Run the backtest for that date**

```bash
.venv/bin/python run.py backtest --start <DATE> --end <DATE+1> --tickers <TICKER>
```

The date range only needs to include the signal date — price data is downloaded
from `start` to the present, so exit prices (`HOLDING_DAYS` later) are always
available.

**3. Verify the numbers independently**

Entry price  = open on the **first trading day after** the signal date  
Exit price   = close **`HOLDING_DAYS` trading days** after the entry day  
Raw return   = `(exit - entry) / entry`  
Alpha        = raw return − SPY return over the same window

**4. Clean up**

```bash
rm ~/.trading-bot/cache/<TICKER>/<DATE>.json
```

### Example

```bash
# Inject a Buy signal for MSFT on 2024-01-02
mkdir -p ~/.trading-bot/cache/MSFT
echo '{"signal": "Buy"}' > ~/.trading-bot/cache/MSFT/2024-01-02.json

# Run
.venv/bin/python run.py backtest --start 2024-01-02 --end 2024-01-03 --tickers MSFT

# Expected output (verified against yfinance):
#   entry  2024-01-03 open  = $362.7610
#   exit   2024-01-10 close = $376.2879
#   raw return = +3.73%,  alpha vs SPY = +2.43%

# Clean up
rm ~/.trading-bot/cache/MSFT/2024-01-02.json
```

### What this covers

- Signal → trade conversion (`SIGNAL_MAP` logic)
- Entry fill: next-day open (realistic EOD-signal simulation)
- Exit fill: close after `HOLDING_DAYS` trading days
- Return and alpha calculation
- CSV output written to `~/.trading-bot/results/`

### What this does NOT cover

- LLM signal quality (use a real backtest date range for that)
- Order execution / broker integration (see `broker.py`)
- Risk controls (see `risk.py`)
