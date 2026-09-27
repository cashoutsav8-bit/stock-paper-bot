# Stock paper bot

Two strategies paper-traded side by side (A and D). B and C were retired on 2026-09-27; their paper history is in `docs/retired/`, $5,000 of paper money each.
**PAPER ONLY**: it never places orders and needs no API key or brokerage account.

| | Strategy | Rules | Backtest |
|---|---|---|---|
| A | Breakout trend | New 126-day closing high while SPY is above its 200-day average; 1% risk per trade, 4×ATR20 trailing stop, max 20 names, max 10% per name | 2003–2026: 12.5%/yr, Sharpe 0.76, max DD −26.6% |
| B | Carry + momentum | Top 50 by dividend-yield rank + 12-1 momentum rank, equal weight, rebuilt monthly; cash when SPY is below its 200-day average | 2003–2026: 8.9%/yr, Sharpe 0.75, max DD −25.7% (2016–26: 10.3%/yr, Sharpe 0.85) |
| D | Leveraged S&P trend | Exposure = 1.5 × share of the last 19 closes SPY finished above its 200-day average (1.5× SPY in uptrends, cash in downtrends); borrowing charged at 5.5%/yr | 1996–2026: 13.0%/yr vs SPY 10.5%, Sharpe 0.74 vs 0.61, max DD −34% vs −55% |
| C | SPY mean reversion | Buy SPY when 2-day RSI < 10 and SPY is above its 200-day average; sell when RSI > 70 | 1999–2026: Sharpe 0.87, max DD −14.8% |

Dashboard: https://cashoutsav8-bit.github.io/stock-paper-bot/ (built from `docs/`).

How it runs: GitHub Actions runs `bot/stock_bot.py` about every 15 minutes on weekdays during the day
(hourly otherwise). Trades are decided on each trading day's official close; runs during the day only
refresh live values and the position-health tables. Data: Yahoo Finance daily bars and the S&P 500
member list from github.com/datasets/s-and-p-500-companies.

Reset a strategy: delete its folder under `docs/` (for example `docs/strat_A`).
