# earnings-cache (ALL symbols, single-call)

Diese Variante lädt **einmal pro Nacht** den **kompletten Earnings-Kalender**
von Finnhub (ein einziger API-Call) für ein wählbares Fenster (z. B. nächste 120 Tage)
und baut daraus einen Index **für alle Symbole**, die dort auftauchen.
Kein Symbol-Download nötig → **unbegrenzte Anzahl** abgedeckt.

## Sparsamkeit / Cache
- Lädt nur, wenn `docs/earnings.json` **älter als M Stunden** ist
  (`FINNHUB_EARNINGS_TTL_HOURS`, Standard 20).
- Nur **1 API-Call** (`/calendar/earnings`) pro Lauf.
- Ergebnis wird nur committet/deployed, wenn sich die Datei geändert hat.
- `.nojekyll` deaktiviert Jekyll-Build.

## Einrichtung
1. Repo anlegen, Dateien hochladen.
2. Secret **FINNHUB_TOKEN** setzen (Settings → Secrets and variables → Actions).
3. Optional-Variablen (Settings → Variables):
   - `FINNHUB_DAYS_AHEAD` — Tage in die Zukunft, Standard `120`
   - `FINNHUB_DAYS_BACK` — Tage zurück, Standard `1`
   - `FINNHUB_EARNINGS_TTL_HOURS` — Standard `20`
4. Settings → Pages → **Build and deployment = GitHub Actions**.
5. Läuft täglich **03:30 UTC**.

## JSON-Format
`docs/earnings.json` ist ein Dictionary `symbol → Objekt` mit dem **nächsten** Termin.
