"""Run: uv run python -m app.backtest.historical_prices --from-date 2025-09-01"""

from app.backtest.data import historical_main

if __name__ == "__main__":
    historical_main()
