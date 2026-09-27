# Stock paper bot

Three S&P 500 strategies paper-traded side by side, $5,000 of paper money each.
**PAPER ONLY**: it never places orders and needs no API key or brokerage account.

| | Strategy | Rules | Backtest |
|---|---|---|---|
| A | Breakout trend | New 126-day closing high while SPY is above its 200-day average; 1% risk per trade, 4×ATR20 trailing stop, max 20 names, max 10% per name | 2003–2026: 12.5%/yr, Sharpe 0.76, max DD −26.6% |
| B | Carry + momentum | Top 50 by dividend-yield rank + 12-1 momentum rank, equal weight, rebuilt monthly; cash when SPY is below its 200-day average | 2003–2026: 11.7%/yr, Sharpe 0.91, max DD −19.7% |
| C | SPY mean reversion | Buy SPY when 2-day RSI < 10 and SPY is above its 200-day average; sell when RSI > 70 | 1999–2026: Sharpe 0.87, max DD −14.8% |

Dashboard: `docs/compare.html` (published with GitHub Pages).

How it runs: GitHub Actions runs `bot/stock_bot.py` about every 15 minutes on weekdays during the day
(hourly otherwise). Trades are decided on each trading day's official close; runs during the day only
refresh live values and the position-health tables. Data: Yahoo Finance daily bars and the S&P 500
member list from github.com/datasets/s-and-p-500-companies.

Reset a strategy: delete its folder under `docs/` (for example `docs/strat_A`).
