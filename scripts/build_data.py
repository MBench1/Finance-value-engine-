#!/usr/bin/env python3
"""
Nightly EDGAR data builder for the Intrinsic Value Engine.

Reads SEC's bulk companyfacts.zip (one JSON per filer) WITHOUT extracting it,
boils each US-listed company down to the inputs the DCF needs, and writes one
tiny JSON per ticker into ./data/ plus an index file.

The picking logic is a direct port of the browser parser shipped inside
index.html (annual 10-K/20-F/40-F rows, 300-400 day duration window, latest
end then latest filed, multi-tag fallback, staleness guard vs the revenue
year). Keep the two in sync if you change either.

Usage (run by the GitHub Actions workflow; can also be run locally):
  python3 scripts/build_data.py companyfacts.zip company_tickers.json data/
"""
import sys, os, json, zipfile, datetime

# tag priority lists — mirror XBRL_TAGS in index.html
TAGS = {
    "rev":   ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
              "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax"],
    "ebit":  ["OperatingIncomeLoss"],
    "ltdNc": ["LongTermDebtNoncurrent"],
    "ltdC":  ["LongTermDebtCurrent"],
    "ltd":   ["LongTermDebt"],
    "stb":   ["ShortTermBorrowings", "CommercialPaper"],
    "cash":  ["CashAndCashEquivalentsAtCarryingValue"],
    "sti":   ["ShortTermInvestments", "MarketableSecuritiesCurrent"],
    "intx":  ["InterestExpense", "InterestExpenseNonoperating", "InterestIncomeExpenseNet"],
    "taxExp": ["IncomeTaxExpenseBenefit"],
    "pretax": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
               "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
    "rnd":   ["ResearchAndDevelopmentExpense"],
    "sbc":   ["ShareBasedCompensation"],
}
DURATION_FIELDS = {"rev", "ebit", "intx", "taxExp", "pretax", "rnd", "sbc"}
ANNUAL_FORMS = ("10-K", "20-F", "40-F")
STALE_DAYS = 550  # drop tags older than this vs the revenue year

def d(s):
    return datetime.date.fromisoformat(s)

def pick_annual_duration(units, pref_cur):
    if not units:
        return None
    curs = [pref_cur] if pref_cur and pref_cur in units else list(units.keys())
    for cur in curs:
        ok = []
        for e in units.get(cur, []):
            if not e.get("start") or not e.get("end") or not isinstance(e.get("val"), (int, float)):
                continue
            if not str(e.get("form", "")).startswith(ANNUAL_FORMS):
                continue
            days = (d(e["end"]) - d(e["start"])).days
            if 300 < days < 400:
                ok.append(e)
        if ok:
            ok.sort(key=lambda e: (e["end"], e.get("filed", "")))
            e = ok[-1]
            return {"val": e["val"], "end": e["end"], "form": e["form"], "cur": cur}
    return None

def pick_latest_instant(units, pref_cur, any_form=False):
    if not units:
        return None
    curs = [pref_cur] if pref_cur and pref_cur in units else list(units.keys())
    for cur in curs:
        ok = [e for e in units.get(cur, [])
              if isinstance(e.get("val"), (int, float)) and e.get("end")
              and (any_form or str(e.get("form", "")).startswith(ANNUAL_FORMS))]
        if ok:
            ok.sort(key=lambda e: (e["end"], e.get("filed", "")))
            e = ok[-1]
            return {"val": e["val"], "end": e["end"], "form": e.get("form"), "cur": cur}
    return None

def extract(facts, pref_cur=None):
    gaap = facts.get("us-gaap", {})
    dei = facts.get("dei", {})
    got = {}
    for field, tags in TAGS.items():
        for tag in tags:
            node = gaap.get(tag)
            if not node:
                continue
            pick = (pick_annual_duration(node.get("units"), pref_cur)
                    if field in DURATION_FIELDS
                    else pick_latest_instant(node.get("units"), pref_cur))
            if pick:
                pick["tag"] = tag
                got[field] = pick
                break
    sh = dei.get("EntityCommonStockSharesOutstanding")
    if sh:
        p = pick_latest_instant(sh.get("units"), None, any_form=True)
        if p:
            got["shares"] = p
    # staleness guard: never mix tags from older fiscal years with the latest
    ref = got.get("rev", got.get("ebit"))
    if ref:
        ref_end = d(ref["end"])
        for k in [k for k in got if k != "shares"]:
            if (ref_end - d(got[k]["end"])).days > STALE_DAYS:
                del got[k]
    return got

def to_row(name, got, built):
    """Collapse extracted tags into the site's company-entry shape (millions)."""
    if "rev" not in got and "ebit" not in got:
        return None
    M = lambda x: round(x / 1e6, 1)
    row = {"nm": name, "built": built}
    ref = got.get("rev", got.get("ebit"))
    row["cur"] = ref["cur"]
    row["fy"] = "Fiscal year ended " + ref["end"] + " (" + ref.get("form", "?") + ")"
    row["end"] = ref["end"]
    if "rev" in got:  row["rev"] = M(got["rev"]["val"])
    if "ebit" in got: row["ebit"] = M(got["ebit"]["val"])
    debt = 0.0
    if "ltdNc" in got: debt += got["ltdNc"]["val"]
    if "ltdC" in got:  debt += got["ltdC"]["val"]
    if "ltdNc" not in got and "ltdC" not in got and "ltd" in got:
        debt += got["ltd"]["val"]
    if "stb" in got:   debt += got["stb"]["val"]
    if debt > 0: row["debt"] = M(debt)
    cash = 0.0
    if "cash" in got: cash += got["cash"]["val"]
    if "sti" in got:  cash += got["sti"]["val"]
    if cash > 0: row["cash"] = M(cash)
    if "shares" in got: row["sh"] = round(got["shares"]["val"] / 1e6, 2)
    if "intx" in got:   row["intx"] = abs(M(got["intx"]["val"]))
    if "taxExp" in got and "pretax" in got and got["pretax"]["val"]:
        rate = got["taxExp"]["val"] / got["pretax"]["val"] * 100
        row["taxe"] = round(min(max(rate, 0), 60), 1)
        if rate < 0 or rate > 60:
            row["note"] = "Effective tax rate was anomalous (%.1f%%) this year; clamped — normalize it yourself." % rate
    if "rnd" in got: row["rnd"] = M(got["rnd"]["val"])
    if "sbc" in got: row["sbc"] = M(got["sbc"]["val"])
    row["src"] = "SEC EDGAR companyfacts (bulk), " + ref.get("form", "10-K")
    return row

def main():
    zpath, tickers_path, outdir = sys.argv[1], sys.argv[2], sys.argv[3]
    os.makedirs(outdir, exist_ok=True)
    built = datetime.date.today().isoformat()
    with open(tickers_path) as f:
        tk_map = json.load(f)
    # company_tickers.json: {"0":{"cik_str":320193,"ticker":"AAPL","title":"Apple Inc."}, ...}
    by_cik = {}
    for v in tk_map.values():
        by_cik.setdefault(int(v["cik_str"]), []).append((v["ticker"].upper(), v.get("title", "")))
    written, skipped, index = 0, 0, []
    with zipfile.ZipFile(zpath) as z:
        names = set(z.namelist())
        for cik, tickers in by_cik.items():
            member = "CIK%010d.json" % cik
            if member not in names:
                skipped += 1
                continue
            try:
                with z.open(member) as f:
                    doc = json.load(f)
            except Exception:
                skipped += 1
                continue
            got = extract(doc.get("facts", {}))
            row = to_row(doc.get("entityName") or tickers[0][1], got, built)
            if not row:
                skipped += 1
                continue
            for ticker, _ in tickers:  # share classes (GOOG/GOOGL) get the same file
                with open(os.path.join(outdir, ticker + ".json"), "w") as f:
                    json.dump(row, f, separators=(",", ":"))
                index.append(ticker)
                written += 1
    with open(os.path.join(outdir, "_index.json"), "w") as f:
        json.dump({"built": built, "count": written, "tickers": sorted(index)}, f)
    print("built=%s written=%d skipped=%d" % (built, written, skipped))

if __name__ == "__main__":
    main()
