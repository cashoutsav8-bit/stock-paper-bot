"""
STOCK PAPER BOT: three strategies run side by side. PAPER ONLY. It never places orders
and needs no API key or brokerage account.

  A  Breakout trend (S&P 500 stocks)
     Buy when the close is the highest of the last 126 trading days and SPY is above its
     200-day average. If more names qualify than there are free slots, take the strongest
     6-month performers first. Size each position so the stop is 1% of equity away
     (4 x ATR20), max 10% of equity per name, max 20 names.
     Stop starts at entry - 4 x ATR20 and trails at the highest close - 4 x ATR20 (it only
     moves up). Exit on a close below the stop.
     Backtest 2003-2026: 12.5%/yr, Sharpe 0.76, worst drawdown -26.6% (SPY -55%).

  B  Carry + momentum (S&P 500 stocks)
     Score = percentile(trailing 12-month dividend yield) + percentile(12-1 month momentum).
     Hold the top 50, equal weight, rebuilt at the first close of each month.
     Hold cash when SPY closes below its 200-day average (checked every day).
     Backtest 2003-2026: 8.9%/yr, Sharpe 0.75, worst drawdown -25.7% (2016-2026: 10.3%/yr, Sharpe 0.85).

  C  SPY mean reversion
     Buy SPY when its 2-day RSI is below 10 and SPY is above its 200-day average.
     Sell when the 2-day RSI rises above 70. Cash otherwise.
     Backtest 1999-2026: Sharpe 0.87, worst drawdown -14.8%, beta 0.11.

Each strategy starts with $5,000 of paper money and fractional shares.
Trades are decided on each trading day's official close (the backtest assumed the same;
live you would send market-on-close orders around 3:50 PM ET). Runs during the day only
refresh live values and position health. Missed days are caught up on the next run.
Costs: 0.10% slippage per side on stocks, 0.05% on SPY. Commissions $0.
"""
import csv, json, math, os, sys
from datetime import datetime, timedelta, timezone
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D

START = 5000.0
SLIP_STOCK, SLIP_ETF = 0.0010, 0.0005
try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:                      # Windows Python without tz data: fall back to a fixed offset
    ET = timezone(timedelta(hours=-4))
HERE = os.environ.get("PAPERBOT_DATA") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")
os.makedirs(HERE, exist_ok=True)

# strategy settings (same as the backtest)
A_LOOK, A_ATR_N, A_ATR_MULT, A_RISK, A_MAXPOS, A_MAXW, A_RANK = 126, 20, 4.0, 0.01, 20, 0.10, 126
B_TOP = 50
C_LOW, C_HIGH = 10, 70
NAMES = {"A": "Breakout trend", "B": "Carry + momentum", "C": "SPY mean reversion"}
DESCR = {
    "A": "S&P 500 stocks at a new 6-month closing high, SPY above its 200-day average. 1% risk per trade, 4&times;ATR trailing stop, max 20 names.",
    "B": "Top 50 S&P 500 stocks by dividend yield + 12-1 momentum, equal weight, rebuilt monthly. Cash when SPY is below its 200-day average.",
    "C": "Buys SPY when its 2-day RSI drops below 10 in an uptrend (SPY above 200-day average). Sells when RSI rises above 70.",
}


# ---------------- helpers ----------------
def now_et():
    if D.OFFLINE and D.OFFLINE_ASOF:
        return datetime.fromisoformat(D.OFFLINE_ASOF).replace(hour=17, tzinfo=ET)
    return datetime.now(ET)

def ds(ts):
    return pd.Timestamp(ts).strftime("%Y-%m-%d")

def append_csv(path, row, header):
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(header)
        w.writerow(row)

def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))

def rsi2(s):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=0.5).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=0.5).mean()
    return 100 - 100 / (1 + up / dn)


class Book:
    def __init__(self, key):
        self.key = key
        self.dir = os.path.join(HERE, f"strat_{key}")
        os.makedirs(self.dir, exist_ok=True)
        self.f = {n: os.path.join(self.dir, n) for n in ("state.json", "events.csv", "equity.csv", "trades.csv", "report.html")}
        if os.path.exists(self.f["state.json"]):
            self.s = json.load(open(self.f["state.json"], encoding="utf-8"))
        else:
            self.s = {"cash": START, "pos": {}, "last_day": None, "started": None, "month": None, "meta": {}}

    def save(self):
        json.dump(self.s, open(self.f["state.json"], "w", encoding="utf-8"), indent=1)

    def log(self, day, sym, ev, detail):
        append_csv(self.f["events.csv"], [day, sym, ev, detail], ["date", "symbol", "event", "detail"])
        print(f"  [{self.key}] {day} {sym:6s} {ev:10s} {detail}")

    def value(self, px):
        return self.s["cash"] + sum(p["sh"] * px.get(t, p["last"]) for t, p in self.s["pos"].items())

    def buy(self, day, t, dollars, price, slip, extra=None, why=""):
        if dollars <= 0.5:
            return
        fill = price * (1 + slip)
        sh = dollars / fill
        self.s["cash"] -= dollars
        p = self.s["pos"].get(t)
        if p:   # add to an existing holding
            tot = p["sh"] + sh
            p["entry"] = (p["entry"] * p["sh"] + fill * sh) / tot
            p["cost"] += dollars
            p["sh"] = tot
        else:
            p = {"sh": sh, "entry": fill, "entry_date": day, "cost": dollars, "last": price, "divs": 0.0}
            self.s["pos"][t] = p
        if extra:
            p.update(extra)
        self.log(day, t, "BUY", f"{sh:.4f} sh @ {fill:.2f} = ${dollars:,.2f}{(' | ' + why) if why else ''}")

    def sell(self, day, t, price, slip, frac=1.0, why=""):
        p = self.s["pos"][t]
        fill = price * (1 - slip)
        sh = p["sh"] * frac
        proceeds = sh * fill
        self.s["cash"] += proceeds
        if frac >= 0.9999:
            pnl = proceeds + p["divs"] - p["cost"]
            ret = pnl / p["cost"] if p["cost"] else 0
            append_csv(self.f["trades.csv"], [t, p["entry_date"], day, round(p["entry"], 4), round(fill, 4),
                                              round(pnl, 2), round(ret * 100, 2), why],
                       ["symbol", "entry_date", "exit_date", "entry", "exit", "pnl_usd", "return_pct", "reason"])
            self.log(day, t, "SELL", f"all @ {fill:.2f}, P&L ${pnl:+,.2f} ({ret:+.1%}) | {why}")
            del self.s["pos"][t]
        else:
            p["cost"] *= (1 - frac)
            p["divs"] *= (1 - frac)
            p["sh"] -= sh
            self.log(day, t, "TRIM", f"{sh:.4f} sh @ {fill:.2f} | {why}")


# ---------------- data ----------------
def complete_days(spy_bars):
    """Trading days whose close is final (drop today's bar until 4:20 PM ET)."""
    n = now_et()
    days = list(spy_bars.index)
    if days and ds(days[-1]) == n.strftime("%Y-%m-%d") and (n.hour, n.minute) < (16, 20):
        days = days[:-1]
    return days

def build_panel(raw):
    close = pd.DataFrame({t: r["bars"]["close"] for t, r in raw.items()}).sort_index()
    adj = pd.DataFrame({t: r["bars"]["adj"] for t, r in raw.items()}).reindex(close.index)
    high = pd.DataFrame({t: r["bars"]["high"] for t, r in raw.items()}).reindex(close.index)
    low = pd.DataFrame({t: r["bars"]["low"] for t, r in raw.items()}).reindex(close.index)
    div = pd.DataFrame({t: r["divs"] for t, r in raw.items() if len(r["divs"])}).reindex(close.index).fillna(0.0)
    div = div.reindex(columns=close.columns, fill_value=0.0)
    spl = {t: r["splits"] for t, r in raw.items() if len(r["splits"])}
    pc = close.shift(1)
    tr = np.fmax(np.fmax((high - low).values, (high - pc).abs().values), (low - pc).abs().values)
    atr = pd.DataFrame(tr, index=close.index, columns=close.columns).rolling(A_ATR_N).mean()
    return dict(close=close, adj=adj, high=high, low=low, div=div, splits=spl, atr=atr,
                hi126=close.rolling(A_LOOK).max(),
                mom126=adj / adj.shift(A_RANK) - 1,
                mom12_1=adj.shift(21) / adj.shift(252) - 1,
                dy=div.rolling(252, min_periods=1).sum() / close,
                nbars=close.notna().cumsum())


# ---------------- strategies ----------------
def corp_actions(book, P, day):
    """Splits: Yahoo re-adjusts all past prices after a split, so compare each holding's stored
    last close with the freshly downloaded close for that same day. A large clean mismatch means a
    split happened: rescale shares and stored prices so the position's dollar value is unchanged.
    (Works the same whether the split is seen live or while catching up missed days.)"""
    prev = book.s["last_day"]
    for t, p in list(book.s["pos"].items()):
        if prev and t in P["close"].columns:
            c_prev = P["close"][t].loc[:pd.Timestamp(prev)].dropna()
            if len(c_prev) and c_prev.iloc[-1] > 0:
                k = p["last"] / float(c_prev.iloc[-1])
                if k > 1.3 or k < 0.77:
                    p["sh"] *= k
                    for f in ("entry", "stop", "hh", "last"):
                        if f in p:
                            p[f] /= k
                    book.log(ds(day), t, "SPLIT", f"prices rescaled by 1/{k:.4g}, shares now {p['sh']:.4f} (value unchanged)")
        if t in P["div"].columns:
            amt = float(P["div"].at[day, t])
            if amt > 0 and ds(day) > p["entry_date"]:
                cash = amt * p["sh"]
                book.s["cash"] += cash
                p["divs"] += cash
                book.log(ds(day), t, "DIVIDEND", f"${amt:.4f}/sh = ${cash:,.2f}")

def px_on(P, t, day):
    v = P["close"].at[day, t] if t in P["close"].columns else np.nan
    return None if pd.isna(v) else float(v)

def step_A(book, P, day, members, spy_ok):
    d = ds(day)
    # 1) exits on the existing stop, then trail the stop
    for t in list(book.s["pos"]):
        p = book.s["pos"][t]
        c = px_on(P, t, day)
        if c is None:
            continue
        p["last"] = c
        if c < p["stop"]:
            book.sell(d, t, c, SLIP_STOCK, why=f"close {c:.2f} below stop {p['stop']:.2f}")
            continue
        p["hh"] = max(p["hh"], c)
        a = P["atr"].at[day, t]
        if not pd.isna(a):
            ns = p["hh"] - A_ATR_MULT * a
            if ns > p["stop"] + 1e-9:
                p["stop"] = ns
    # 2) entries
    if not spy_ok or len(book.s["pos"]) >= A_MAXPOS:
        return
    px = {t: p["last"] for t, p in book.s["pos"].items()}
    eq = book.value(px)
    row_c, row_hi, row_a, row_m = P["close"].loc[day], P["hi126"].loc[day], P["atr"].loc[day], P["mom126"].loc[day]
    cand = [t for t in members if t in row_c.index and t not in book.s["pos"]
            and not pd.isna(row_c[t]) and not pd.isna(row_a[t]) and not pd.isna(row_m[t])
            and P["nbars"].at[day, t] >= A_LOOK and row_c[t] >= row_hi[t]]
    cand.sort(key=lambda t: -row_m[t])
    for t in cand[:A_MAXPOS - len(book.s["pos"])]:
        c, a = float(row_c[t]), float(row_a[t])
        w = min(A_RISK * eq / (A_ATR_MULT * a) * c / eq, A_MAXW)
        val = w * eq
        if val > book.s["cash"]:
            book.log(d, t, "SKIP", f"not enough cash (${book.s['cash']:,.0f} for ${val:,.0f})")
            break
        book.buy(d, t, val, c, SLIP_STOCK, extra={"stop": c - A_ATR_MULT * a, "hh": c, "atr_at_entry": a},
                 why=f"new 126-day high, 6m return {row_m[t]:+.0%}, stop {c - A_ATR_MULT * a:.2f} ({A_ATR_MULT*a/c:.1%} away)")

def step_B(book, P, day, members, spy_ok):
    d = ds(day)
    for t, p in book.s["pos"].items():
        c = px_on(P, t, day)
        if c is not None:
            p["last"] = c
    if not spy_ok:
        if book.s["pos"]:
            for t in list(book.s["pos"]):
                book.sell(d, t, book.s["pos"][t]["last"], SLIP_STOCK, why="SPY closed below its 200-day average: go to cash")
        book.s["month"] = None      # rebuild as soon as the trend is back
        return
    month = d[:7]
    if book.s.get("month") == month and book.s["pos"]:
        return
    # rebuild the basket
    elig = [t for t in members if t in P["close"].columns and P["nbars"].at[day, t] >= 240
            and not pd.isna(P["mom12_1"].at[day, t]) and not pd.isna(P["close"].at[day, t])]
    sc = pd.DataFrame({"dy": P["dy"].loc[day, elig].fillna(0), "mom": P["mom12_1"].loc[day, elig]})
    sc["score"] = sc.dy.rank(pct=True) + sc.mom.rank(pct=True)
    top = sc.sort_values("score", ascending=False).head(B_TOP)
    book.s["meta"]["last_ranks"] = {t: int(i + 1) for i, t in enumerate(sc.sort_values("score", ascending=False).index[:150])}
    target = set(top.index)
    for t in list(book.s["pos"]):
        if t not in target:
            book.sell(d, t, book.s["pos"][t]["last"], SLIP_STOCK, why="dropped out of the top 50 at the monthly rebuild")
    px = {t: p["last"] for t, p in book.s["pos"].items()}
    eq = book.value(px)
    tgt = eq / B_TOP * 0.999
    for t in top.index:   # trim overweights first so the cash is there for buys
        p = book.s["pos"].get(t)
        if p and p["sh"] * p["last"] > tgt * 1.02:
            book.sell(d, t, p["last"], SLIP_STOCK, frac=1 - tgt / (p["sh"] * p["last"]), why="monthly rebalance to equal weight")
    for t in top.index:
        c = float(P["close"].at[day, t])
        have = book.s["pos"][t]["sh"] * c if t in book.s["pos"] else 0.0
        need = min(tgt - have, book.s["cash"])
        if need > tgt * 0.02:
            book.buy(d, t, need, c, SLIP_STOCK,
                     why=f"yield {top.at[t, 'dy']:.1%}, 12-1 momentum {top.at[t, 'mom']:+.0%}" if t not in book.s["pos"] else "monthly rebalance to equal weight")
    book.s["month"] = month

def step_C(book, P, day, spy_ok, rsi):
    d = ds(day)
    c = float(P["close"].at[day, "SPY"])
    if "SPY" in book.s["pos"]:
        book.s["pos"]["SPY"]["last"] = c
        if rsi > C_HIGH:
            book.sell(d, "SPY", c, SLIP_ETF, why=f"2-day RSI {rsi:.0f} > {C_HIGH}")
    elif rsi < C_LOW and spy_ok:
        book.buy(d, "SPY", book.s["cash"], c, SLIP_ETF, why=f"2-day RSI {rsi:.1f} < {C_LOW} with SPY above its 200-day average")


# ---------------- main ----------------
def main():
    n = now_et()
    print(f"Stock paper bot run {n:%Y-%m-%d %H:%M} ET (PAPER ONLY, no orders are placed)")
    books = {k: Book(k) for k in "ABC"}
    spy = D.fetch_many(["SPY"])["SPY"]
    days = complete_days(spy["bars"])
    last_done = min((b.s["last_day"] or "9999") for b in books.values())
    todo_needed = any(b.s["last_day"] is None or b.s["last_day"] < ds(days[-1]) for b in books.values())
    held = sorted({t for b in books.values() for t in b.s["pos"]} - {"SPY"})
    if todo_needed:
        members = [m for m in D.sp500_members() if m != "SPY"]
        tickers = sorted(set(members) | set(held))
        print(f"New close to process ({ds(days[-1])}). Downloading {len(tickers)} stocks...")
        raw = D.fetch_many(tickers)
        missing = [t for t in tickers if t not in raw]
        if len(missing) > 0.2 * len(tickers):
            raise RuntimeError(f"Data download failed for {len(missing)} of {len(tickers)} symbols; trying again next run.")
        if missing:
            print(f"  no data for {len(missing)}: {', '.join(missing[:15])}")
        raw["SPY"] = spy
        P = build_panel(raw)
        spy_adj = P["adj"]["SPY"]
        spy_sma = spy_adj.rolling(200).mean()
        rsi = rsi2(spy_adj)
        members = [m for m in members if m in raw]
        for key, b in books.items():
            if b.s["last_day"] is None:
                b.s["last_day"] = ds(days[-2])
                b.s["started"] = ds(days[-1])
                print(f"[{key}] First run: starting with ${START:,.0f} at the {ds(days[-1])} close.")
        for day in days:
            if day not in P["close"].index:
                continue
            for key, b in books.items():
                if ds(day) <= b.s["last_day"]:
                    continue
                spy_ok = bool(spy_adj.loc[day] > spy_sma.loc[day])
                corp_actions(b, P, day)
                if key == "A":
                    step_A(b, P, day, members, spy_ok)
                elif key == "B":
                    step_B(b, P, day, members, spy_ok)
                else:
                    step_C(b, P, day, spy_ok, float(rsi.loc[day]))
                px = {t: p["last"] for t, p in b.s["pos"].items()}
                eq = b.value(px)
                append_csv(b.f["equity.csv"], [ds(day), round(eq, 2), len(b.s["pos"]), round(b.s["cash"], 2),
                                                round(float(P["close"].at[day, "SPY"]), 2)],
                           ["date", "equity", "positions", "cash", "spy_close"])
                b.s["last_day"] = ds(day)
        ctx = dict(spy_ok=bool(spy_adj.iloc[-1] > spy_sma.iloc[-1]), spy=float(P["close"]["SPY"].loc[days[-1]]),
                   spy_sma=float(spy_sma.loc[days[-1]] * P["close"]["SPY"].loc[days[-1]] / spy_adj.loc[days[-1]]),
                   rsi=float(rsi.loc[days[-1]]), last_day=ds(days[-1]),
                   b_ranks=books["B"].s["meta"].get("last_ranks", {}))
        json.dump(ctx, open(os.path.join(HERE, "context.json"), "w"), indent=1)
    else:
        print(f"Closes are up to date ({ds(days[-1])}). Refreshing live prices only.")
    # live marks for the report
    held = sorted({t for b in books.values() for t in b.s["pos"]} - {"SPY"})
    live_raw = D.fetch_many(held, rng="5d") if held else {}
    live = {t: float(r["live"]) for t, r in live_raw.items() if r.get("live")}
    if spy.get("live"):
        live["SPY"] = float(spy["live"])
    ctx = json.load(open(os.path.join(HERE, "context.json"))) if os.path.exists(os.path.join(HERE, "context.json")) else {}
    for b in books.values():
        b.save()
    import report
    report.write_all(books, live, ctx, spy["bars"], n)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        print("ERROR:", e)
        sys.exit(1)
