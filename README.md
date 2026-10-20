# SMC scanner

Scans a watchlist and reports instruments whose latest candle is **TOUCHING** or **NEAR** a
fresh order block (OB) or fair value gap (FVG), scored 0-4 for confluence with market
structure, the Fibonacci OTE band and a swing trendline.

**Screening only.** The code never places, modifies or closes orders. `tests/test_readonly.py`
walks the package's AST and fails if any MetaTrader5 call outside the read-only allow-list
appears. Log in with the account's **investor (read-only) password** so that guarantee does
not depend on code alone.

## Install

Windows (the `MetaTrader5` package only ships Windows wheels; csv and demo sources work anywhere):

```bash
uv sync
```

## Run

```bash
uv run smc-scan --demo                       # simulated prices, no terminal needed
uv run smc-scan --source mt5 --tf 1h         # live, from the watchlist
uv run smc-scan --source mt5 --symbols EURUSD XAUUSD --tf 15m --every 15
uv run smc-scan --source csv --symbols data/eurusd_1h.csv
```

Options: `--tf` (5m/15m/30m/1h/4h/1d), `--bars` (500, 15-5000), `--swing` (10), `--near`
(0.5 ATR), `--all-touches` (include zones touched before), `--every N` (rescan every N
minutes), `--out` (CSV path, default `scan_results.csv`), `--watchlist` (default
`watchlist.yaml`, or `SMC_WATCHLIST`).

Exit code 1 when no symbol could be loaded at all (terminal down, bad login); the previous
CSV is then left untouched so an outage never looks like "no hits". In `--every` mode a
failed cycle is logged and the loop continues.

### API

```bash
uv run uvicorn smc_scanner.api:app --host 127.0.0.1 --port 8000
# GET /scan?source=mt5&tf=1h&symbols=EURUSD,XAUUSD&bars=500&swing=10&near=0.5&all_touches=false
```

Only the Next.js server calls this API (see below); the browser never does, so there is no
CORS. Bind to loopback: requests whose `Host` is not in `SMC_API_ALLOWED_HOSTS` (default
`127.0.0.1,localhost`) get a 400, and when `SMC_INTERNAL_KEY` is set every request must carry
it in `X-Internal-Key` (unset means open on loopback). Sources are `mt5` and `demo` (the csv
source takes file paths, so it is CLI-only). Symbols are validated against
`[A-Za-z0-9._#@-]{1,32}`, at most 50 per request. Scans are serialised with a lock because
the MT5 connection is process-wide. `GET /scan` returns `rows` and per-symbol `failures`
(503 when nothing could be loaded); `GET /config` returns choices, defaults, limits and the
watchlist for the scan form. Every error body is `{ "success": false, "error": "..." }`.

## Web page (`nextjs-frontend/`)

A Next.js 16 page at `/scan` that runs the same scan through the API and shows the rows with
status and bias pills, score pips, the skipped symbols, an auto-rescan (`?every=N` minutes)
and a CSV download (`/scan/export`, same columns as the CLI). The form is a GET form, so every
scan has a shareable URL and the page works without JavaScript.

```bash
cd nextjs-frontend && npm install && copy .env.example .env.local
uv run uvicorn smc_scanner.api:app --host 127.0.0.1 --port 8000   # from the repo root
npm run dev                                                         # http://localhost:3000/scan
```

It follows StoreCart's conventions: the browser never calls FastAPI; server-only wrappers in
`src/lib/api/` (`scan.ts` over `server.ts`'s `callBackend`) call the client generated from
`openapi.json` into `src/lib/api/generated/` (never edited; ESLint blocks imports of it outside
`src/lib/api` and tests). After an API change:

```bash
uv run python -m smc_scanner.openapi_export      # writes nextjs-frontend/openapi.json
cd nextjs-frontend && npm run generate:client    # regenerates src/lib/api/generated
```

`pytest tests/test_openapi.py` and `npm run check:client` fail while either is stale.
Checks: `npm run lint && npm run typecheck && npm run test:coverage` (Vitest, 80% thresholds).
There is no Playwright suite yet.

### MetaTrader 5

The loader attaches to the MT5 terminal installed on this machine with `mt5.initialize()`.
If the terminal is already open and logged in, nothing else is needed. Otherwise the
optional variables in `.env.example` (`MT5_PATH`, `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`)
let it start the terminal and log in; starting a terminal from cold takes about a minute.
A failed login is not retried for the remaining symbols of that scan.

Symbol names are broker-specific (`EURUSD`, `XAUUSD`, `USTEC`/`NAS100`/`US100`, `UK100`,
`BTCUSD`, sometimes with suffixes such as `.r` or `m`). Put them in `watchlist.yaml` exactly
as Market Watch shows them; unknown symbols are logged and skipped. `symbol_select` adds a
scanned symbol to Market Watch. Candle times are broker server time.

The latest candle is the **still-forming bar**, so TOUCHING/NEAR and the price can change
until it closes. A warning is logged when the last bar is more than two timeframes behind
the symbol's last tick (closed market or dead feed).

### CSV

Header `time,open,high,low,close[,volume]`, ISO-8601 times, any order (sorted on load).

## Logic (per instrument, on the latest candle)

Detection uses [smartmoneyconcepts](https://github.com/joshyattridge/smart-money-concepts)
(`swing_highs_lows`, `fvg`, `ob`). Everything else is the scanner's own rule set:

1. ATR(14) = mean true range of the last 14 candles.
2. **Confirmed swings**: the library's first/last-candle tags are ignored; a swing counts only
   if it is at index > 0 and at least `--swing` candles before the latest candle.
3. **Bias**: HH + HL bullish, LH + LL bearish, else range (equal levels are range).
4. **OTE** (0.618-0.786): bullish from the last confirmed swing low to the highest high since;
   bearish mirrored.
5. **Trendline** through the last two confirmed swing lows (bullish) or highs (bearish),
   projected to the latest candle.
6. **Zones**
   - FVG: skipped unless fully formed before the latest candle; touches count from two
     candles after the middle candle.
   - OB: touches count only after price has first moved entirely away from the block. Edges
     are the block candle's exact high and low (the library's float32 values are not used).
   - Invalidated when a candle before the latest one traded through the far side (wick), or
     when the latest close sits beyond the far side without overlapping.
   - Fresh only by default (`prior_touches == 0`); `--all-touches` includes tested zones.
   - TOUCHING = latest candle overlaps the zone. NEAR = within `--near` ATR of the near edge.
7. **Score** out of 4: aligned with bias; overlaps the OTE band of its direction; trendline
   holds (latest low above the swing-low line for bullish, mirrored for bearish); an OB and
   an FVG of the same direction overlap in price.

Rows are sorted TOUCHING first, then score, then distance, and written to CSV with the
columns `instrument, status, zone, zone_low, zone_high, price, dist_atr, bias, in_ote,
trendline_ok, ob_fvg, score, zone_age, prior_touches, bar_time`.

## Develop

```bash
uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run pytest
```

`pytest` enforces 80% branch coverage. Tests use hand-built OHLC: a fresh bullish FVG touched
on the last candle is reported, a previously tested gap is not (unless `--all-touches`), a
gap price traded through is not, NEAR at 0.4 ATR is reported and 0.6 ATR is not, a bearish
FVG mirrors all of that, an OB overlap before the move-away is not a touch, an equal-price
OB retest counts, and the MT5 loader is exercised through a fake module.
