#!/usr/bin/env python3
import os, json, sys, pathlib, datetime, time
import requests

# ---------- ENV & Defaults ----------
FINNHUB_TOKEN = os.environ.get("FINNHUB_TOKEN", "").strip()
if not FINNHUB_TOKEN:
    print("ERROR: FINNHUB_TOKEN is not set.", file=sys.stderr)
    sys.exit(1)

def getenv_int(name, default):
    v = os.environ.get(name, "")
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default

EARNINGS_TTL_HOURS = getenv_int("FINNHUB_EARNINGS_TTL_HOURS", 24)
DAYS_AHEAD         = getenv_int("FINNHUB_DAYS_AHEAD", 365)
DAYS_BACK          = getenv_int("FINNHUB_DAYS_BACK", 7)

# USA + wichtige EU-Börsen (kannst du in Repo-Variables überschreiben)
DEFAULT_EXCHANGES = "US,DE,PA,LSE,AS,MI,MC,STO,SWX"
EXCHANGES = os.environ.get("FINNHUB_EXCHANGES", DEFAULT_EXCHANGES)

# ---------- Paths ----------
ROOT       = pathlib.Path(__file__).resolve().parents[1]
DOCS_DIR   = ROOT / "docs"
DOCS_DIR.mkdir(parents=True, exist_ok=True)
# deaktiviert Jekyll auf Pages
(DOCS_DIR / ".nojekyll").write_text("", encoding="utf-8")

SYMBOLS_CACHE = DOCS_DIR / "symbols_cache.json"
OUTPUT_JSON   = DOCS_DIR / "earnings.json"
LAST_RUN      = DOCS_DIR / "last_run.txt"
STATS_JSON    = DOCS_DIR / "stats.json"

API_BASE = "https://finnhub.io/api/v1"

TODAY     = datetime.date.today()
FROM_DATE = (TODAY - datetime.timedelta(days=DAYS_BACK)).strftime("%Y-%m-%d")
TO_DATE   = (TODAY + datetime.timedelta(days=DAYS_AHEAD)).strftime("%Y-%m-%d")

# ---------- Helpers ----------
def file_age_hours(path: pathlib.Path) -> float:
    if not path.exists():
        return 1e9
    return (time.time() - path.stat().st_mtime) / 3600.0

def month_ranges(start_date: datetime.date, end_date: datetime.date):
    """Zerlegt [start,end] in Monatsfenster (inklusive)."""
    cur = datetime.date(start_date.year, start_date.month, 1)
    end = datetime.date(end_date.year, end_date.month, 1)
    out = []
    while cur <= end:
        if cur.month == 12:
            nxt = datetime.date(cur.year + 1, 1, 1)
        else:
            nxt = datetime.date(cur.year, cur.month + 1, 1)
        last = nxt - datetime.timedelta(days=1)
        frm = max(cur, start_date)
        to  = min(last, end_date)
        out.append((frm.strftime("%Y-%m-%d"), to.strftime("%Y-%m-%d")))
        cur = nxt
    return out

def fetch_symbols_from_exchanges(ex_list):
    all_syms = []
    for ex in ex_list:
        ex = ex.strip()
        if not ex:
            continue
        url = f"{API_BASE}/stock/symbol"
        params = {"exchange": ex, "token": FINNHUB_TOKEN}
        try:
            r = requests.get(url, params=params, timeout=60)
            r.raise_for_status()
            data = r.json() or []
        except Exception as e:
            print(f"WARN: symbol fetch failed for {ex}: {e}", file=sys.stderr)
            continue
        for row in data:
            sym = (row.get("symbol") or "").strip()
            typ = (row.get("type") or "").lower()
            if not sym:
                continue
            # ETFs/Funds raus
            if "etf" in typ or "fund" in typ:
                continue
            all_syms.append(sym)
    return sorted(set(all_syms))

def load_symbols_cached(exchanges, ttl_days=7) -> set:
    # verwende Cache, wenn frisch und gleiche Exchanges
    if SYMBOLS_CACHE.exists():
        age_days = (time.time() - SYMBOLS_CACHE.stat().st_mtime) / 86400.0
        try:
            data = json.loads(SYMBOLS_CACHE.read_text(encoding="utf-8"))
            cached_ex = data.get("meta", {}).get("exchanges", [])
            if age_days < ttl_days and sorted(cached_ex) == sorted(exchanges):
                return set(data.get("symbols", []))
        except Exception:
            pass
    # neu laden & cachen
    syms = fetch_symbols_from_exchanges(exchanges)
    SYMBOLS_CACHE.write_text(json.dumps({
        "meta": {"exchanges": exchanges, "generatedUtc": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"},
        "symbols": syms
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return set(syms)

def fetch_calendar_range(from_date, to_date):
    url = f"{API_BASE}/calendar/earnings"
    params = {"from": from_date, "to": to_date, "token": FINNHUB_TOKEN}
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    return r.json() or {}

def normalize_time_flag(row_time):
    if not row_time:
        return "tbd"
    val = str(row_time).strip().lower()
    if val in ("bmo", "amc"):
        return val
    return "tbd"

def build_index_all(calendar_json):
    """Map symbol -> nächster Termin (nur kommende)."""
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
            "lastUpdatedUtc": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        }
    return out

def write_stats(count: int, universe_count: int = None, rows_total: int = None, rows_after_filter: int = None):
    stats = {
        "count": count,
        "daysAhead": DAYS_AHEAD,
        "daysBack": DAYS_BACK,
        "lastUpdatedUtc": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    }
    if universe_count is not None:   stats["universeCount"] = universe_count
    if rows_total is not None:       stats["calendarRowsFetched"] = rows_total
    if rows_after_filter is not None:stats["calendarRowsAfterFilter"] = rows_after_filter
    STATS_JSON.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------- Main ----------
def main():
    # Wenn Cache frisch: keine API-Calls, aber stats.json/last_run aktualisieren
    if file_age_hours(OUTPUT_JSON) < EARNINGS_TTL_HOURS:
        try:
            current = json.loads(OUTPUT_JSON.read_text(encoding="utf-8"))
            write_stats(len(current))
        except Exception:
            write_stats(0)
        LAST_RUN.write_text(datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), encoding="utf-8")
        print(f"Cache fresh: {OUTPUT_JSON} age < {EARNINGS_TTL_HOURS}h — skipping fetch.")
        return

    # (1) Symbol-Universum (USA/EU) — 1x/Woche frisch
    ex_list = [e.strip() for e in EXCHANGES.split(",") if e.strip()]
    sym_universe = load_symbols_cached(ex_list, ttl_days=7)

       # (2) Kalender monatsweise abrufen und zusammenführen
    start = datetime.datetime.strptime(FROM_DATE, "%Y-%m-%d").date()
    end   = datetime.datetime.strptime(TO_DATE, "%Y-%m-%d").date()
    all_rows = []
    for frm, to in month_ranges(start, end):
        cal = fetch_calendar_range(frm, to)
        rows = cal.get("earningsCalendar") or []
        all_rows.extend(rows)

    # (3) Nur USA/EU Symbole behalten
    filtered_rows = [r for r in all_rows if (r.get("symbol") or "").strip() in sym_universe]
    filtered = {"earningsCalendar": filtered_rows}

    # (4) Index bauen
    idx = build_index_all(filtered)

    # (5) Schreiben, nur wenn geändert
    new_json = json.dumps(idx, ensure_ascii=False, indent=2, sort_keys=True)
    old_json = OUTPUT_JSON.read_text(encoding="utf-8") if OUTPUT_JSON.exists() else ""
    if new_json != old_json:
        OUTPUT_JSON.write_text(new_json, encoding="utf-8")
        print(f"Updated {OUTPUT_JSON} with {len(idx)} symbols.")
    else:
        print("No changes in earnings.json; keep existing.")

    # (6) Stats & last_run immer aktualisieren
    write_stats(
        len(idx),
        universe_count=len(sym_universe),
        rows_total=len(all_rows),
        rows_after_filter=len(filtered_rows),
    )
    LAST_RUN.write_text(datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), encoding="utf-8")


if __name__ == "__main__":
    main()
