"""
Market data for the stock paper bot. Free, no API key.

  Daily bars   : Yahoo Finance chart API (split-adjusted OHLC, adjusted close, dividends, splits)
  Universe     : current S&P 500 members from github.com/datasets/s-and-p-500-companies
  Live prices  : Yahoo chart API "regularMarketPrice" (about 15 min delayed at most)

OFFLINE mode (PAPERBOT_OFFLINE=path/to/prices.parquet) replays a local dataset instead.
It is only used for testing the bot against the backtest.
"""
import csv, io, json, os, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import pandas as pd

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}
UNIVERSE_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
YAHOO = "https://query{n}.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1d&events=div%7Csplit&includeAdjustedClose=true"
OFFLINE = os.environ.get("PAPERBOT_OFFLINE")
OFFLINE_ASOF = os.environ.get("PAPERBOT_ASOF")   # replay: pretend "today" is this date


def get(url, tries=4, timeout=20):
    last = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # 429 / timeouts: back off and retry
            last = e
            time.sleep(1.5 * (k + 1))
    raise last


def yahoo_sym(t):
    return t.replace(".", "-")          # BRK.B -> BRK-B


def sp500_members():
    if OFFLINE:
        m = pd.read_parquet(os.path.join(os.path.dirname(OFFLINE), "members.parquet"))
        asof = pd.Timestamp(OFFLINE_ASOF) if OFFLINE_ASOF else m.date.max()
        last = m[m.date <= asof].date.max()
        return sorted(m[m.date == last].ticker.tolist())
    raw = get(UNIVERSE_URL).decode()
    rows = list(csv.DictReader(io.StringIO(raw)))
    return sorted({r["Symbol"].strip() for r in rows if r.get("Symbol")})


def _parse_chart(j):
    r = j["chart"]["result"][0]
    ts = r.get("timestamp") or []
    q = r["indicators"]["quote"][0]
    adj = (r["indicators"].get("adjclose") or [{}])[0].get("adjclose") or q["close"]
    gmt = r["meta"].get("gmtoffset", -14400)
    idx = [datetime.fromtimestamp(t + gmt, timezone.utc).strftime("%Y-%m-%d") for t in ts]
    df = pd.DataFrame({"open": q["open"], "high": q["high"], "low": q["low"], "close": q["close"],
                       "adj": adj, "volume": q.get("volume")}, index=pd.to_datetime(idx))
    df = df[~df.index.duplicated(keep="last")].dropna(subset=["close"])
    ev = r.get("events") or {}
    divs = pd.Series({pd.Timestamp(datetime.fromtimestamp(int(v["date"]) + gmt, timezone.utc).strftime("%Y-%m-%d")): float(v["amount"])
                      for v in (ev.get("dividends") or {}).values()}, dtype=float)
    splits = pd.Series({pd.Timestamp(datetime.fromtimestamp(int(v["date"]) + gmt, timezone.utc).strftime("%Y-%m-%d")):
                        float(v["numerator"]) / float(v["denominator"])
                        for v in (ev.get("splits") or {}).values() if float(v.get("denominator") or 0) > 0}, dtype=float)
    live = r["meta"].get("regularMarketPrice")
    return {"bars": df.sort_index(), "divs": divs.sort_index(), "splits": splits.sort_index(), "live": live}


def fetch_one(sym, rng="2y"):
    for n in (1, 2):
        try:
            j = json.loads(get(YAHOO.format(n=n, sym=yahoo_sym(sym), rng=rng)))
            if j.get("chart", {}).get("result"):
                return _parse_chart(j)
        except Exception:
            pass
    return None


_OFF = None
def _offline():
    global _OFF
    if _OFF is None:
        d = pd.read_parquet(OFFLINE)
        d = d[d.close > 0]
        _OFF = {t: g.set_index("date").sort_index() for t, g in d.groupby("ticker")}
    return _OFF


def fetch_many(tickers, rng="2y", workers=8):
    """Returns {ticker: {"bars", "divs", "splits", "live"}}; tickers that fail are left out."""
    if OFFLINE:
        off, out = _offline(), {}
        asof = pd.Timestamp(OFFLINE_ASOF) if OFFLINE_ASOF else None
        for t in tickers:
            g = off.get(t)
            if g is None:
                continue
            if asof is not None:
                g = g[g.index <= asof]
            g = g.iloc[-520:]
            if g.empty:
                continue
            bars = pd.DataFrame({"open": g.open, "high": g.high, "low": g.low, "close": g.close,
                                 "adj": g.adj_close, "volume": g.volume})
            out[t] = {"bars": bars, "divs": g.dividends[g.dividends > 0], "splits": g.stock_splits[g.stock_splits > 0],
                      "live": float(g.close.iloc[-1])}
        return out
    out = {}
    with ThreadPoolExecutor(workers) as ex:
        for t, res in zip(tickers, ex.map(lambda s: fetch_one(s, rng), tickers)):
            if res is not None and len(res["bars"]):
                out[t] = res
    return out
