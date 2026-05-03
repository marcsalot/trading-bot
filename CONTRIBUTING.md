# Contributing

## Getting started

1. Clone the repo and follow the setup steps in [README.md](README.md).
2. Create a feature branch from `main`:
   ```bash
   git checkout -b feat/your-feature-name
   ```
3. Make your changes, test them (see below), then open a pull request against `main`.

## Branch naming

| Prefix | Use for |
|---|---|
| `feat/` | New features |
| `fix/` | Bug fixes |
| `docs/` | Documentation only |
| `refactor/` | Code restructuring with no behaviour change |
| `test/` | Adding or improving tests |

## Code style

- Follow [PEP 8](https://peps.python.org/pep-0008/). Use 4-space indentation.
- Keep lines under 100 characters.
- Add docstrings to all public functions and modules.
- Do not commit secrets, API keys, or `.env` files — these are blocked by `.gitignore`.

## Testing

Before opening a PR, verify any changes to `backtest.py` using the cache-injection technique:

```bash
# Inject a known signal
mkdir -p ~/.trading-bot/cache/<TICKER>
echo '{"signal": "Buy"}' > ~/.trading-bot/cache/<TICKER>/<DATE>.json

# Run backtest and confirm trade appears with correct prices/returns
.venv/bin/python run.py backtest --start <DATE> --end <DATE+1> --tickers <TICKER>

# Clean up
rm ~/.trading-bot/cache/<TICKER>/<DATE>.json
```

See [TESTING.md](TESTING.md) for the full procedure and a worked example.

For changes to `live_trader.py`, use `--now` mode against your Alpaca paper account:

```bash
.venv/bin/python run.py live --now
```

## Configuration changes

If you add a new setting to `config.py`:
- Give it a sensible default so existing setups are unaffected.
- Add it to the settings table in `README.md`.
- Document the valid range / accepted values in a comment next to the setting.

## Pull request checklist

Before requesting review, confirm:

- The backtest runs without errors over at least one date range
- Any new logic is covered by a cache-injection test
- `README.md` and/or `TESTING.md` are updated if behaviour changed
- No secrets or runtime data (`~/.trading-bot/`) are included in the diff

## Commit messages

Use the format `<type>: <short summary>` on the first line, with an optional body:

```
feat: add stop-loss support to live_trader

Closes positions immediately when unrealised loss exceeds a configurable
threshold, before the normal HOLDING_DAYS exit.
```

Common types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`.
