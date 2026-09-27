"""
Research data pull. Runs inside GitHub Actions (open internet) and writes to ./out, which the
workflow pushes to the `research-data` branch. Nothing here trades.

  universe.csv        every NYSE / Nasdaq / NYSE American registrant from the SEC ticker file
  insider.parquet     open-market insider purchases and sales (Form 4, SEC bulk data sets, 2006+)
  fundamentals.parquet  quarterly XBRL facts from the SEC "frames" API (2009+)
  prices_close.parquet  daily adjusted close, 2008+, wide (date x ticker), float32
  prices_dvol.parquet   daily dollar volume, same shape
  extra_prices.parquet  BTC, ETH, MSTR, GLD, TLT, SPY, QQQ, IWM ... for cross-asset work
  log.txt / status.json progress and errors
"""
import io, json, os, sys, time, zipfile, traceback, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import numpy as np, pandas as pd

OUT = os.environ.get("OUT", "out")
os.makedirs(OUT, exist_ok=True)
SEC_UA = {"User-Agent": "stock-paper-bot research cashoutsav8-bit@users.noreply.github.com", "Accept-Encoding": "identity"}
WEB_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}
LOG = open(os.path.join(OUT, "log.txt"), "a", encoding="utf-8")
STATUS = {}


def log(*a):
    msg = f"[{datetime.now(timezone.utc):%H:%M:%S}] " + " ".join(str(x) for x in a)
    print(msg, flush=True)
    LOG.write(msg + "\n"); LOG.flush()


def status(k, v):
    STATUS[k] = v
    json.dump(STATUS, open(os.path.join(OUT, "status.json"), "w"), indent=1, default=str)


def get(url, headers, tries=5, timeout=60, pause=0.0):
    last = None
    for k in range(tries):
        try:
            if pause:
                time.sleep(pause)
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 404:
                raise
            time.sleep(2 * (k + 1))
        except Exception as e:
            last = e
            time.sleep(2 * (k + 1))
    raise last


# ---------------- 1. universe ----------------
def universe():
    j = json.loads(get("https://www.sec.gov/files/company_tickers_exchange.json", SEC_UA))
    df = pd.DataFrame(j["data"], columns=j["fields"])
    df.columns = [c.lower() for c in df.columns]
    df = df[df.exchange.isin(["Nasdaq", "NYSE", "NYSE American", "NYSE MKT", "NYSE Arca"])].copy()
    df["ticker"] = df.ticker.str.upper().str.strip()
    df = df.drop_duplicates("ticker")
    df.to_csv(os.path.join(OUT, "universe.csv"), index=False)
    log("universe:", len(df), "tickers;", df.exchange.value_counts().to_dict())
    status("universe", len(df))
    return df


# ---------------- 2. insider transactions ----------------
def insider():
    frames = []
    now = datetime.now(timezone.utc)
    for y in range(2006, now.year + 1):
        for q in range(1, 5):
            if (y, q) > (now.year, (now.month - 1) // 3 + 1):
                break
            data = None; last = None
            for base in ("structureddata", "datastandardsinnovation"):
                url = f"https://www.sec.gov/files/{base}/data/insider-transactions-data-sets/{y}q{q}_form345.zip"
                try:
                    data = get(url, SEC_UA, tries=3, timeout=120, pause=0.2)
                    break
                except Exception as e:
                    last = e
            if data is None:
                log(f"insider {y}q{q}: not available ({last})")
                continue
            try:
                z = zipfile.ZipFile(io.BytesIO(data))
                names = {n.upper().split("/")[-1]: n for n in z.namelist()}
                def rd(tbl, cols):
                    n = names.get(f"{tbl}.TSV")
                    t = pd.read_csv(z.open(n), sep="\t", dtype=str, usecols=lambda c: c.upper() in cols,
                                    on_bad_lines="skip", quoting=3, encoding_errors="replace")
                    t.columns = [c.upper() for c in t.columns]
                    return t
                sub = rd("SUBMISSION", {"ACCESSION_NUMBER", "FILING_DATE", "DOCUMENT_TYPE", "ISSUERCIK", "ISSUERTRADINGSYMBOL"})
                own = rd("REPORTINGOWNER", {"ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNER_RELATIONSHIP", "RPTOWNER_TITLE"})
                tr = rd("NONDERIV_TRANS", {"ACCESSION_NUMBER", "TRANS_DATE", "TRANS_CODE", "TRANS_SHARES", "TRANS_PRICEPERSHARE",
                                           "TRANS_ACQUIRED_DISP_CD", "SHRS_OWND_FOLWNG_TRANS", "DIRECT_INDIRECT_OWNERSHIP"})
                tr = tr[tr.TRANS_CODE.isin(["P", "S"])]
                own = own.groupby("ACCESSION_NUMBER").agg(RPTOWNERCIK=("RPTOWNERCIK", "first"),
                                                         RPTOWNER_RELATIONSHIP=("RPTOWNER_RELATIONSHIP", "first"),
                                                         RPTOWNER_TITLE=("RPTOWNER_TITLE", "first"),
                                                         N_OWNERS=("RPTOWNERCIK", "count")).reset_index()
                m = tr.merge(sub, on="ACCESSION_NUMBER", how="left").merge(own, on="ACCESSION_NUMBER", how="left")
                frames.append(m)
                log(f"insider {y}q{q}: {len(m)} P/S rows")
            except Exception as e:
                log(f"insider {y}q{q}: parse error {e}")
    df = pd.concat(frames, ignore_index=True)
    for c in ("FILING_DATE", "TRANS_DATE"):
        df[c] = pd.to_datetime(df[c], format="%d-%b-%Y", errors="coerce")
    for c in ("TRANS_SHARES", "TRANS_PRICEPERSHARE", "SHRS_OWND_FOLWNG_TRANS"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["VALUE"] = df.TRANS_SHARES * df.TRANS_PRICEPERSHARE
    df.columns = [c.lower() for c in df.columns]
    df.to_parquet(os.path.join(OUT, "insider.parquet"), index=False)
    log("insider total rows:", len(df), "purchases:", int((df.trans_code == "P").sum()))
    status("insider_rows", len(df))


# ---------------- 3. fundamentals (XBRL frames) ----------------
DURATION = [("us-gaap", "Revenues", "USD"), ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax", "USD"),
            ("us-gaap", "SalesRevenueNet", "USD"), ("us-gaap", "NetIncomeLoss", "USD"), ("us-gaap", "OperatingIncomeLoss", "USD"),
            ("us-gaap", "GrossProfit", "USD")]
INSTANT = [("us-gaap", "Assets", "USD"), ("us-gaap", "StockholdersEquity", "USD"), ("us-gaap", "Liabilities", "USD"),
           ("us-gaap", "CashAndCashEquivalentsAtCarryingValue", "USD"), ("dei", "EntityCommonStockSharesOutstanding", "shares")]


def fundamentals():
    now = datetime.now(timezone.utc)
    jobs = []
    for y in range(2009, now.year + 1):
        for tax, c, u in DURATION:
            jobs.append((tax, c, u, f"CY{y}"))
            jobs += [(tax, c, u, f"CY{y}Q{q}") for q in range(1, 5)]
        for tax, c, u in INSTANT:
            jobs += [(tax, c, u, f"CY{y}Q{q}I") for q in range(1, 5)]
    rows = []
    def one(job):
        tax, c, u, per = job
        url = f"https://data.sec.gov/api/xbrl/frames/{tax}/{c}/{u}/{per}.json"
        try:
            j = json.loads(get(url, SEC_UA, tries=3, timeout=60, pause=0.12))
        except Exception:
            return []
        return [(c, per, d.get("cik"), d.get("end"), d.get("val"), d.get("accn")) for d in j.get("data", [])]
    with ThreadPoolExecutor(4) as ex:            # stay well under the SEC's 10 requests/second
        for k, res in enumerate(ex.map(one, jobs)):
            rows += res
            if k % 100 == 0:
                log(f"frames {k}/{len(jobs)} rows so far {len(rows)}")
    df = pd.DataFrame(rows, columns=["concept", "period", "cik", "end", "val", "accn"])
    df["end"] = pd.to_datetime(df.end, errors="coerce")
    df["val"] = pd.to_numeric(df.val, errors="coerce")
    df.to_parquet(os.path.join(OUT, "fundamentals.parquet"), index=False)
    log("fundamentals rows:", len(df), df.concept.value_counts().to_dict())
    status("fundamental_rows", len(df))


# ---------------- 4. prices ----------------
P1 = int(datetime(2008, 1, 1, tzinfo=timezone.utc).timestamp())
def yahoo(sym):
    s = sym.replace(".", "-").replace("/", "-")
    for n in (1, 2):
        url = (f"https://query{n}.finance.yahoo.com/v8/finance/chart/{s}?period1={P1}&period2={int(time.time())}"
               f"&interval=1d&events=div%7Csplit&includeAdjustedClose=true")
        try:
            j = json.loads(get(url, WEB_UA, tries=3, timeout=30))
            r = j["chart"]["result"][0]
            ts = r.get("timestamp")
            if not ts:
                return None
            q = r["indicators"]["quote"][0]
            adj = (r["indicators"].get("adjclose") or [{}])[0].get("adjclose") or q["close"]
            idx = pd.to_datetime(pd.Series(ts), unit="s").dt.normalize()
            d = pd.DataFrame({"adj": adj, "close": q["close"], "vol": q["volume"]}, index=idx.values)
            d = d[~d.index.duplicated(keep="last")].dropna(subset=["adj"])
            return d
        except Exception:
            continue
    return None


def prices(tickers, name, workers=8):
    closes, dvols, fails = {}, {}, []
    t0 = time.time()
    with ThreadPoolExecutor(workers) as ex:
        for k, (t, d) in enumerate(zip(tickers, ex.map(yahoo, tickers))):
            if d is None or len(d) < 5:
                fails.append(t)
            else:
                closes[t] = d.adj.astype("float32")
                dvols[t] = (d.close * d.vol).astype("float32")
            if k % 250 == 0:
                log(f"prices {name}: {k}/{len(tickers)} ok={len(closes)} fail={len(fails)} {time.time()-t0:.0f}s")
    C = pd.DataFrame(closes).sort_index()
    V = pd.DataFrame(dvols).reindex(C.index)
    log(f"prices {name}: done ok={len(closes)} fail={len(fails)} shape={C.shape}")
    return C, V, fails


def save_wide(df, path):
    df.columns = [str(c) for c in df.columns]
    df.to_parquet(path)
    mb = os.path.getsize(path) / 1e6
    if mb > 90:           # GitHub's per-file limit is 100 MB: split by columns
        os.remove(path)
        half = len(df.columns) // 2
        save_wide(df.iloc[:, :half], path.replace(".parquet", "_a.parquet"))
        save_wide(df.iloc[:, half:], path.replace(".parquet", "_b.parquet"))
    else:
        log(f"saved {path} {mb:.1f} MB")


def main():
    steps = sys.argv[1:] or ["universe", "extra", "insider", "fundamentals", "prices"]
    status("started", datetime.now(timezone.utc))
    u = None
    for step in steps:
        try:
            log("=== step", step)
            if step == "universe":
                u = universe()
            elif step == "extra":
                ex = ["SPY", "QQQ", "IWM", "IWC", "GLD", "TLT", "IEF", "UUP", "MSTR", "COIN", "BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "^VIX"]
                C, V, f = prices(ex, "extra", workers=4)
                C.to_parquet(os.path.join(OUT, "extra_prices.parquet"))
            elif step == "insider":
                insider()
            elif step == "fundamentals":
                fundamentals()
            elif step == "prices":
                if u is None:
                    u = pd.read_csv(os.path.join(OUT, "universe.csv"))
                C, V, fails = prices(list(u.ticker), "universe")
                save_wide(C, os.path.join(OUT, "prices_close.parquet"))
                save_wide(V, os.path.join(OUT, "prices_dvol.parquet"))
                pd.Series(fails).to_csv(os.path.join(OUT, "price_failures.csv"), index=False)
                status("price_tickers", C.shape[1])
            status(f"done_{step}", datetime.now(timezone.utc))
        except Exception as e:
            log(f"STEP {step} FAILED: {e}")
            LOG.write(traceback.format_exc())
            status(f"failed_{step}", str(e))
    status("finished", datetime.now(timezone.utc))


if __name__ == "__main__":
    main()
