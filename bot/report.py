"""HTML pages for the stock paper bot: one page per strategy plus a comparison page."""
import os, shutil
from datetime import datetime
import pandas as pd

START = 5000.0

CSS = """body{font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;background:#10141a;color:#e9eef3;max-width:1000px;margin:0 auto;padding:24px 16px}
h1{font-size:26px;margin:0} h2{font-size:17px;margin:30px 0 8px} .muted{color:#98a6b3} a{color:#8cbcf0}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-top:16px}
.tile{border-top:2px solid #e9eef3;padding-top:6px} .tile b{font:700 22px ui-monospace,Consolas,monospace;display:block}
table{border-collapse:collapse;width:100%;font-size:13.5px} td,th{padding:6px 8px;border-bottom:1px solid #26303a;text-align:left;white-space:nowrap}
th{color:#8795a3;font-size:11.5px;text-transform:uppercase;letter-spacing:.03em} .n{text-align:right;font-family:ui-monospace,Consolas,monospace}
.wrap{overflow-x:auto} .pos{color:#5cc98a} .neg{color:#ef7a79} .warn{color:#e8b25a}
.nav{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 18px}.nav a{color:#e9eef3;text-decoration:none;border:1px solid #26303a;border-radius:6px;padding:5px 10px;font-size:13px}.nav a.on{background:#26303a}
.box{border:1px solid #26303a;border-radius:8px;padding:12px 14px;margin-top:14px} .box p{margin:4px 0}
.pill{display:inline-block;font:600 11px/1 ui-monospace,monospace;padding:3px 6px;border-radius:4px;background:#26303a}
.pill.ok{background:#1c3b2c;color:#79d9a3}.pill.close{background:#3f3219;color:#f0c374}.pill.bad{background:#40211f;color:#f39a93}"""

COLORS = {"A": "#5b9fe8", "B": "#e3a15a", "C": "#5cc4ae", "ALL": "#e9eef3", "SPY": "#7c8b99"}


def f2(x): return f"{x:,.2f}"
def cls(x): return "pos" if x >= 0 else "neg"


def nav(prefix, on):
    items = [("compare.html", "Comparison", "cmp")] + [(f"strat_{k}/report.html", f"{k}: {n}", k) for k, n in
                                                       (("A", "Breakout trend"), ("B", "Carry + momentum"), ("C", "SPY mean reversion"))]
    return "<div class=nav>" + "".join(f'<a class="{"on" if key == on else ""}" href="{prefix}{h}">{t}</a>' for h, t, key in items) + "</div>"


def read_csv(path):
    import csv
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def line_chart(series, W=900, H=220, pct=True):
    """series: list of (label, color, [values]) plotted as % change from the first value."""
    ss = [(l, c, [v / vals[0] - 1 for v in vals] if pct else vals) for l, c, vals in series if len(vals) >= 1]
    if not ss:
        return ""
    allv = [v for _, _, vs in ss for v in vs] + [0]
    lo, hi = min(allv), max(allv)
    pad = max((hi - lo) * 0.1, 0.002)
    lo, hi = lo - pad, hi + pad
    n = max(len(vs) for _, _, vs in ss)
    L, R, T, B = 52, 118, 10, 22
    X = lambda i: L + (W - L - R) * (i / max(1, n - 1))
    Y = lambda v: T + (H - T - B) * (1 - (v - lo) / (hi - lo))
    g = [f'<line x1="{L}" x2="{W-R}" y1="{Y(0):.1f}" y2="{Y(0):.1f}" stroke="#55606b" stroke-dasharray="4 4"/>'
         f'<text x="{L-6}" y="{Y(0)+4:.1f}" fill="#8795a3" font-size="11" text-anchor="end">0%</text>']
    for v in (lo + pad, hi - pad):
        if abs(Y(v) - Y(0)) > 14:
            g.append(f'<text x="{L-6}" y="{Y(v)+4:.1f}" fill="#8795a3" font-size="11" text-anchor="end">{v:+.1%}</text>')
    ends = []
    for l, c, vs in ss:
        if len(vs) == 1:
            g.append(f'<circle cx="{X(0):.1f}" cy="{Y(vs[0]):.1f}" r="3" fill="{c}"/>')
        else:
            pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(vs))
            g.append(f'<polyline points="{pts}" fill="none" stroke="{c}" stroke-width="{2.6 if l=="All 3" else 1.8}"/>')
        ends.append([Y(vs[-1]), l, c, vs[-1], X(len(vs) - 1)])
    ends.sort()
    for j in range(1, len(ends)):
        if ends[j][0] - ends[j - 1][0] < 13:
            ends[j][0] = ends[j - 1][0] + 13
    for y, l, c, v, x in ends:
        g.append(f'<text x="{W-R+6}" y="{y+4:.1f}" fill="{c}" font-size="11.5" font-family="ui-monospace,monospace">{l} {v:+.1%}</text>')
    return f'<svg viewBox="0 0 {W} {H}" style="width:100%;height:auto">{"".join(g)}</svg>'


def spy_close_on(spy_bars, d):
    s = spy_bars["close"]
    s = s[s.index <= pd.Timestamp(d)]
    return float(s.iloc[-1]) if len(s) else None


def health_rows(key, b, live, ctx, spy_bars, eq_live):
    rows, notes = [], []
    spy_live = live.get("SPY") or float(spy_bars["close"].iloc[-1])
    today = pd.Timestamp(ctx.get("last_day") or spy_bars.index[-1])
    for t, p in sorted(b.s["pos"].items(), key=lambda kv: kv[1]["sh"] * (live.get(kv[0]) or kv[1]["last"]) - kv[1]["cost"]):
        lv = live.get(t) or p["last"]
        mv = lv / p["entry"] - 1
        s0 = spy_close_on(spy_bars, p["entry_date"])
        spy_mv = (spy_live / s0 - 1) if s0 else 0.0
        rel = mv - spy_mv
        upnl = p["sh"] * lv - p["cost"] + p.get("divs", 0)
        days = max(0, int((today - pd.Timestamp(p["entry_date"])).days))
        weight = p["sh"] * lv / eq_live if eq_live else 0
        if key == "A":
            dist = lv / p["stop"] - 1
            trig = f"stop {p['stop']:.2f}"
            state = "bad" if dist <= 0 else ("close" if dist < 0.03 else "ok")
            dist_s = f"{dist:+.1%} above stop" if dist > 0 else "BELOW stop: exits at today's close if it stays there"
        elif key == "B":
            r = ctx.get("b_ranks", {}).get(t)
            gap = ctx["spy"] / ctx["spy_sma"] - 1 if ctx.get("spy_sma") else 0
            trig = f"rank #{r}" if r else "rank 150+"
            state = "ok" if (r and r <= 50 and gap > 0.02) else ("close" if gap > 0 else "bad")
            dist_s = f"SPY {gap:+.1%} vs 200-day avg; " + ("in top 50" if r and r <= 50 else "outside top 50 at last rebuild")
        else:
            trig = f"RSI2 now {ctx.get('rsi', 0):.0f}"
            state = "ok"
            dist_s = f"sells when RSI2 &gt; 70"
        why = "moving with the market" if abs(rel) < 0.02 else ("stock-specific weakness" if rel < 0 else "stock-specific strength")
        rows.append(f"<tr><td><b>{t}</b></td><td>{p['entry_date']}</td><td class=n>{days}</td><td class=n>{p['entry']:.2f}</td>"
                    f"<td class=n>{lv:.2f}</td><td class='n {cls(mv)}'>{mv:+.1%}</td><td class=n>{spy_mv:+.1%}</td>"
                    f"<td>{why}</td><td class='n {cls(upnl)}'>{upnl:+,.2f}</td><td class=n>{weight:.1%}</td>"
                    f"<td><span class='pill {state}'>{trig}</span></td><td>{dist_s}</td></tr>")
        notes.append((upnl, t, mv, spy_mv, why))
    return rows, notes


def strategy_page(key, name, descr, b, live, ctx, spy_bars, now):
    eq_rows = read_csv(b.f["equity.csv"])
    trades = read_csv(b.f["trades.csv"])
    events = read_csv(b.f["events.csv"])
    px_close = {t: p["last"] for t, p in b.s["pos"].items()}
    eq_close = b.value(px_close)
    eq_live = b.value({t: live.get(t, p["last"]) for t, p in b.s["pos"].items()})
    wins = [t for t in trades if float(t["pnl_usd"]) > 0]
    rows, notes = health_rows(key, b, live, ctx, spy_bars, eq_live)
    total_open = sum(n[0] for n in notes)
    drags = [n for n in notes if n[0] < 0][:3]
    helps = sorted([n for n in notes if n[0] > 0], reverse=True)[:3]
    why_html = ""
    if notes:
        def fmt(n): return f"<b>{n[1]}</b> {n[0]:+,.2f} (stock {n[2]:+.1%} vs SPY {n[3]:+.1%}: {n[4]})"
        why_html = (f"<div class=box><p><b>Why the open positions are {'up' if total_open >= 0 else 'down'}</b> "
                    f"(<span class={cls(total_open)}>{total_open:+,.2f}</span> unrealized, live)</p>"
                    + (f"<p>Biggest drags: {'; '.join(fmt(n) for n in drags)}</p>" if drags else "")
                    + (f"<p>Biggest helps: {'; '.join(fmt(n) for n in helps)}</p>" if helps else "")
                    + "<p class=muted>A position down with SPY also down is market beta and is normal. Stock-specific weakness is what the exit rule is there for. "
                    + {"A": "The trailing stop cuts a loser at about 1% of the account; nothing else needs to be done by hand.",
                       "B": "B holds 50 names equally, so one bad stock is 2% of the basket. It only sells at the monthly rebuild or if SPY breaks its 200-day average.",
                       "C": "C holds SPY for a few days after a sharp dip. It has no stop by design; its exit is the RSI bounce."}[key]
                    + "</p></div>")
    gate = ctx.get("spy_ok")
    gate_html = (f"<p class=muted>Market filter: SPY {ctx.get('spy', 0):.2f} vs 200-day average {ctx.get('spy_sma', 0):.2f}: "
                 f"<b class={'pos' if gate else 'neg'}>{'uptrend: new buys allowed' if gate else 'below: no new buys' + (' and B is in cash' if key == 'B' else '')}</b>."
                 + (f" SPY 2-day RSI: <b>{ctx.get('rsi', 0):.1f}</b> (buy &lt; 10, sell &gt; 70)." if key == "C" else "") + "</p>") if ctx else ""
    tr_rows = "".join(f"<tr><td>{t['symbol']}</td><td>{t['entry_date']}</td><td>{t['exit_date']}</td>"
                      f"<td class='n {cls(float(t['pnl_usd']))}'>{float(t['pnl_usd']):+,.2f}</td><td class=n>{float(t['return_pct']):+.1f}%</td><td>{t['reason']}</td></tr>"
                      for t in reversed(trades[-60:])) or "<tr><td colspan=6>No closed trades yet</td></tr>"
    ev_rows = "".join(f"<tr><td>{e['date']}</td><td>{e['symbol']}</td><td>{e['event']}</td><td style='white-space:normal'>{e['detail']}</td></tr>"
                      for e in list(reversed(events))[:50]) or "<tr><td colspan=4>No events yet</td></tr>"
    ret, lret = eq_close / START - 1, eq_live / START - 1
    chart = line_chart([(key, COLORS[key], [START] + [float(r["equity"]) for r in eq_rows]),
                        ("SPY", COLORS["SPY"], ([float(eq_rows[0]["spy_close"])] if eq_rows else []) + [float(r["spy_close"]) for r in eq_rows])])
    html = f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="120"><title>{key}: {name}</title>
<style>{CSS}</style>{nav('../', key)}
<h1>{key}: {name}</h1>
<p class=muted>{descr} PAPER ONLY, no real orders. Started {b.s['started']} with ${START:,.0f}. Closes processed through {b.s['last_day']}.</p>
{gate_html}
<div class=tiles>
<div class=tile><b class={cls(ret)}>${f2(eq_close)}</b><span class=muted>equity at last close ({ret:+.2%})</span></div>
<div class=tile><b class={cls(lret)}>${f2(eq_live)}</b><span class=muted>live value ({lret:+.2%}) at {now:%b %d %I:%M %p} ET</span></div>
<div class=tile><b>{len(b.s['pos'])}</b><span class=muted>open positions</span></div>
<div class=tile><b>${f2(b.s['cash'])}</b><span class=muted>cash ({b.s['cash']/max(eq_live,1):.0%})</span></div>
<div class=tile><b>{len(trades)}</b><span class=muted>closed trades ({len(wins)} wins)</span></div>
</div>
<h2>Equity vs SPY since start (daily closes)</h2>{chart}
<h2>Position health</h2>{why_html}
<div class=wrap><table><tr><th>Symbol</th><th>Entered</th><th class=n>Days</th><th class=n>Entry</th><th class=n>Live</th><th class=n>Move</th><th class=n>SPY same period</th><th>Read</th><th class=n>Unrealized $</th><th class=n>% of acct</th><th>Exit trigger</th><th>Distance to exit</th></tr>
{''.join(rows) or '<tr><td colspan=12>No open positions</td></tr>'}</table></div>
<h2>Closed trades</h2><div class=wrap><table><tr><th>Symbol</th><th>Entry</th><th>Exit</th><th class=n>P&amp;L</th><th class=n>Return</th><th>Reason</th></tr>{tr_rows}</table></div>
<h2>Recent events</h2><div class=wrap><table><tr><th>Date</th><th>Symbol</th><th>Event</th><th>Detail</th></tr>{ev_rows}</table></div>
<p class=muted style="margin-top:24px">Slippage 0.10% per side on stocks, 0.05% on SPY, $0 commissions, fractional shares. Dividends are credited as cash on the ex-date. Live prices can be delayed up to 15 minutes.</p>"""
    open(b.f["report.html"], "w", encoding="utf-8").write(html)
    return dict(key=key, name=name, eq=eq_close, live=eq_live, n=len(b.s["pos"]), trades=len(trades), wins=len(wins),
                curve=[START] + [float(r["equity"]) for r in eq_rows], dates=[r["date"] for r in eq_rows],
                spy=[float(r["spy_close"]) for r in eq_rows], started=b.s["started"])


def write_all(books, live, ctx, spy_bars, now):
    from stock_bot import NAMES, DESCR, HERE
    res = [strategy_page(k, NAMES[k], DESCR[k], b, live, ctx, spy_bars, now) for k, b in books.items()]
    n = min(len(r["curve"]) for r in res)
    tot = [sum(r["curve"][-n:][i] for r in res) for i in range(n)]
    spy_curve = ([res[0]["spy"][0]] + res[0]["spy"]) if res[0]["spy"] else []
    series = [(f"{r['key']}", COLORS[r["key"]], r["curve"]) for r in res] + [("All 3", COLORS["ALL"], tot)]
    if spy_curve:
        series.append(("SPY", COLORS["SPY"], spy_curve))
    tot_eq, tot_live = sum(r["eq"] for r in res), sum(r["live"] for r in res)
    spy_ret = (spy_curve[-1] / spy_curve[0] - 1) if spy_curve else 0
    spy_live_ret = (live.get("SPY", spy_curve[-1]) / spy_curve[0] - 1) if spy_curve else 0
    rows = "".join(
        f"<tr><td><a href='strat_{r['key']}/report.html'>{r['key']}: {r['name']}</a></td><td class=n>${f2(r['eq'])}</td>"
        f"<td class='n {cls(r['eq']/START-1)}'>{r['eq']/START-1:+.2%}</td><td class='n {cls(r['live']/START-1)}'>{r['live']/START-1:+.2%}</td>"
        f"<td class=n>{r['n']}</td><td class=n>{r['trades']} ({r['wins']} W)</td></tr>" for r in res)
    rows += (f"<tr><td><b>All 3 combined</b></td><td class=n><b>${f2(tot_eq)}</b></td><td class='n {cls(tot_eq/(3*START)-1)}'><b>{tot_eq/(3*START)-1:+.2%}</b></td>"
             f"<td class='n {cls(tot_live/(3*START)-1)}'><b>{tot_live/(3*START)-1:+.2%}</b></td><td class=n>{sum(r['n'] for r in res)}</td><td class=n>{sum(r['trades'] for r in res)}</td></tr>"
             f"<tr><td class=muted>SPY buy &amp; hold (benchmark)</td><td></td><td class='n {cls(spy_ret)}'>{spy_ret:+.2%}</td><td class='n {cls(spy_live_ret)}'>{spy_live_ret:+.2%}</td><td></td><td></td></tr>")
    gate = ctx.get("spy_ok")
    html = f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="120"><title>Stock Paper Bot</title>
<style>{CSS}</style>{nav('', 'cmp')}
<h1>Stock paper bot</h1>
<p class=muted>Three S&amp;P 500 strategies, $5,000 of paper money each. PAPER ONLY, no real orders. Trades are decided on each day's official close; live values refresh every ~15 minutes during market hours. Updated {now:%b %d %I:%M %p} ET, closes through {ctx.get('last_day','-')}.</p>
<p class=muted>Market filter: SPY {ctx.get('spy',0):.2f} vs 200-day average {ctx.get('spy_sma',0):.2f}: <b class={'pos' if gate else 'neg'}>{'uptrend' if gate else 'downtrend'}</b>. SPY 2-day RSI {ctx.get('rsi',0):.1f}.</p>
<div class=tiles>
<div class=tile><b class={cls(tot_eq/(3*START)-1)}>${f2(tot_eq)}</b><span class=muted>all 3 at last close ({tot_eq/(3*START)-1:+.2%})</span></div>
<div class=tile><b class={cls(tot_live/(3*START)-1)}>${f2(tot_live)}</b><span class=muted>all 3 live ({tot_live/(3*START)-1:+.2%})</span></div>
<div class=tile><b class={cls(spy_ret)}>{spy_ret:+.2%}</b><span class=muted>SPY over the same days</span></div>
</div>
<h2>Return since start (daily closes)</h2>{line_chart(series)}
<div class=wrap><table><tr><th>Strategy</th><th class=n>Equity (close)</th><th class=n>Return (close)</th><th class=n>Return (live)</th><th class=n>Positions</th><th class=n>Closed trades</th></tr>{rows}</table></div>
<div class=box><p><b>What to expect</b></p>
<p>Backtest 2008-2026 for the three combined: about 9.5%/yr, Sharpe 0.93, worst drawdown -16%. They lag SPY in strong melt-up years (2019, 2023) and protect in selloffs (2008, 2022).</p>
<p>Judge them after 6-8 weeks, not days. A has the widest swings: in the backtest it gave back 23% between late June and late September 2026, close to its worst drawdown on record.</p></div>"""
    open(os.path.join(HERE, "compare.html"), "w", encoding="utf-8").write(html)
    shutil.copyfile(os.path.join(HERE, "compare.html"), os.path.join(HERE, "index.html"))
    print(f"\nAll 3: ${tot_eq:,.2f} ({tot_eq/(3*START)-1:+.2%}) at the close, ${tot_live:,.2f} live. Pages: {os.path.join(HERE, 'compare.html')}")
    for r in res:
        print(f"  {r['key']} {r['name']:20s} ${r['eq']:,.2f} ({r['eq']/START-1:+.2%})  positions {r['n']}")
