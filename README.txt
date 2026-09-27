STOCK PAPER BOT  (paper only: never places orders, needs no API key)

Strategies running side by side, $5,000 of paper money each
  A  Breakout trend: S&P 500 stocks at a new 6-month closing high while SPY is above its
     200-day average. 1% risk per trade, 4 x ATR trailing stop, max 20 names.   -> docs\strat_A
  B  Carry + momentum: top 50 by dividend yield + 12-1 momentum, equal weight, rebuilt monthly.
     Cash when SPY is below its 200-day average.                                -> docs\strat_B
  C  SPY mean reversion: buy SPY when 2-day RSI < 10 in an uptrend, sell when RSI > 70.
                                                                                -> docs\strat_C
  Compare all three against SPY:                                                -> docs\compare.html

Where it runs
  The live copy runs on GitHub (repo: stock-paper-bot), about every 15 minutes on weekdays.
  Trades are decided on each trading day's official close. Intraday runs refresh live values
  and the "Position health" tables (why each position is up or down, and how far it is from
  its exit).

This folder
  bot\          the code (same as on GitHub)
  docs\         pages and state when you run it locally
  run_paper_bot.bat   optional: run it once on this computer (backup/testing only).
                      Local results are separate from the GitHub copy.

Research write-up: "Stock Alpha Playbook" in your Claude artifacts.
Reset a strategy: delete its folder in docs\ (for example docs\strat_A).
