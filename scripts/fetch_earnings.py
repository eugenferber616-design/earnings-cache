#!/usr/bin/env python3
import os, json, sys, pathlib, datetime, time
import requests

FINNHUB_TOKEN = os.environ.get("FINNHUB_TOKEN", "").strip()
if not FINNHUB_TOKEN:
    print("ERROR: FINNHUB_TOKEN is not set.", file=sys.stderr)
    sys.exit(1)

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "docs"
DOCS_DIR.mkdir(parents=True, exist_ok=True)
(DOCS_DIR / ".nojekyll").write_text("", encoding="utf-8")

OUTPUT_JSON = DOCS_DIR / "earnings.json"
LAST_RUN = DOCS_DIR / "last_run.txt"

def getenv_int(name, default):
    v = os.environ.get(name, "").strip()
    try:
        return int(v)
    except (TypeError, ValueError):
        return default

EARNINGS_TTL_HOURS = getenv_int("FINNHUB_EARNINGS_TTL_HOURS", 20)
DAYS_AHEAD         = getenv_int("FINNHUB_DAYS_AHEAD", 120)
DAYS_BACK          = getenv_int("FINNHUB_DAYS_BACK", 1)


TODAY = datetime.date.today()
FROM_DATE = (TODAY - datetime.timedelta(days=DAYS_BACK)).strftime("%Y-%m-%d")
TO_DATE = (TODAY + datetime.timedelta(days=DAYS_AHEAD)).strftime("%Y-%m-%d")
API_BASE = "https://finnhub.io/api/v1"

def file_age_hours(path):
    if not path.exists():
        return 1e9
    return (time.time() - path.stat().st_mtime) / 3600.0

def fetch_calendar(from_date, to_date):
    url = f"{API_BASE}/calendar/earnings"
    params = {"from": from_date, "to": to_date, "token": FINNHUB_TOKEN}
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    return r.json()

def normalize_time_flag(row_time):
    if not row_time:
        return "tbd"
    val = str(row_time).strip().lower()
    if val in ("bmo", "amc"):
        return val
    return "tbd"

def build_index_all(calendar_json):
    # Build map: symbol -> next upcoming earnings date for all symbols present
    rows = calendar_json.get("earningsCalendar") or []
    by_symbol = {}
    today = datetime.date.today()

    for r in rows:
        sym = (r.get("symbol") or "").strip()
        d = r.get("date")
        if not sym or not d:
            continue
        try:
            dt = datetime.datetime.strptime(d, "%Y-%m-%d").date()
        except Exception:
            continue
        if dt < today:
            continue
        by_symbol.setdefault(sym, []).append((dt, r))

    out = {}
    for sym, items in by_symbol.items():
        items.sort(key=lambda t: t[0])
        best_date = items[0][0]
        same_day = [it for dt, it in items if dt == best_date]
        out[sym] = {
            "symbol": sym,
            "nextEarningsDate": best_date.strftime("%Y-%m-%d"),
            "time": normalize_time_flag(same_day[0].get("time") if same_day else None),
            "finnhubCount": len(same_day),
            "lastUpdatedUtc": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        }
    return out

def main():
    # Skip fetch if earnings cache is still fresh
    if file_age_hours(OUTPUT_JSON) < EARNINGS_TTL_HOURS:
        print(f"Cache fresh: {OUTPUT_JSON} age < {EARNINGS_TTL_HOURS}h — skipping fetch.")
        return

    cal = fetch_calendar(FROM_DATE, TO_DATE)
    idx = build_index_all(cal)

    new_json = json.dumps(idx, ensure_ascii=False, indent=2, sort_keys=True)
    old_json = OUTPUT_JSON.read_text(encoding="utf-8") if OUTPUT_JSON.exists() else ""
    if new_json != old_json:
        OUTPUT_JSON.write_text(new_json, encoding="utf-8")
        print(f"Updated {OUTPUT_JSON} with {len(idx)} symbols.")
    else:
        print("No changes in earnings.json; keep existing.")

    LAST_RUN.write_text(datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), encoding="utf-8")

if __name__ == "__main__":
    main()
