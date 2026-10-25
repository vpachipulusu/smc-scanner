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

Endpoints (all except `/health` need `X-Internal-Key` when `SMC_INTERNAL_KEY` is set; the authoritative
contract is `nextjs-frontend/openapi.json`):

| Method and path | Purpose |
|---|---|
| `GET /health`, `GET /config` | liveness; scan-form choices, defaults, limits, watchlist |
| `GET /scan` | scan only (rate limited: 20 per 60 s) |
| `POST /analyse` | scan, then AI verdicts for the best hits (6 per 60 s; spends money) |
| `GET /analyses`, `GET /analyses/{id}` | stored verdicts, newest first; `limit` (50, max 200) and opaque `cursor` |
| `GET/POST /schedules`, `GET/PATCH/DELETE /schedules/{id}` | saved schedules (at most 50) |
| `POST /schedules/{id}/run` | run once now; 409 if running or a scan holds the lock, 429 + `Retry-After` within 10 s of the last run. A failed run still answers 200 with `status: "failed"`; read the job log |
| `GET /schedules/{id}/logs` | job log, newest first, `limit` (50, max 100) and `cursor` |
| `POST /telegram/test` | send a fixed test message (503 without `TELEGRAM_BOT_TOKEN`, 422 without a chat id, 429 within 5 s of the last, 502 if Telegram refuses) |
| `POST /backtests` | start a walk-forward backtest of one strategy in the background: 202 with the pending row and `Location`. 409 while one runs, 422 for `csv`, bad input or a run over the cost cap (symbols x bars² / stride), 503 if the database is unusable; 6 per 60 s |
| `GET /backtests`, `GET /backtests/{id}` | summaries newest first (`strategy`, `limit` 50, max 200); one run with its status (`pending`, `running`, `done`, `failed`) and results. Poll the id until done |
| `GET /strategies/{slug}/backtest` | the latest finished run of a strategy as a badge (verdict, out-of-sample expectancy and interval); 404 when there is none |

`POST /analyse` also answers 502 when the provider fails for the whole run, and run-now 503 while
the scheduler shuts down.

Backtests run one at a time per process on a background thread, so run the API with a single
worker (a warning is logged otherwise): a second worker would mark the first one's run failed.
A run left unfinished by a restart is marked failed at the next startup.

#### Environment variables

Copy `.env.example` to `.env` (loaded at startup by the API and CLI); it lists names only.

| Variable | Meaning |
|---|---|
| `MT5_PATH`, `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER` | optional terminal start and login (investor password) |
| `SMC_WATCHLIST` | watchlist file, default `watchlist.yaml` |
| `SMC_API_ALLOWED_HOSTS` | accepted `Host` headers, default `127.0.0.1,localhost` |
| `SMC_API_HOST` / `UVICORN_HOST` | tell the startup check which address you bind to (the server cannot see it) |
| `SMC_INTERNAL_KEY` | shared secret for `X-Internal-Key`; must equal `BACKEND_INTERNAL_KEY` in the frontend |
| `ANTHROPIC_API_KEY` | required for `--ai` and `POST /analyse` |
| `AI_PROVIDER` (only `claude`), `AI_MODEL` (default `claude-sonnet-5-5`), `AI_TIMEOUT_SECONDS` (60), `AI_MAX_RETRIES` (2, max 5), `AI_TEMPERATURE`, `AI_BASE_URL` | provider tuning |
| `AI_MAX_CALLS_PER_DAY`, `AI_MAX_COST_PER_DAY` | daily AI caps in calls and estimated USD, per UTC day; blank is unlimited |
| `SMC_DB_PATH` | SQLite file for analyses, schedules, alerts and the job log, default `./smc.db` |
| `SMC_SCHEDULER` | `1`/`true`/`yes`/`on` enables the scheduler; anything else (an unknown value logs a warning) leaves it off |
| `SMC_SERVER_TZ` | IANA zone of the broker clock for 4h/1d schedules, default UTC |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Telegram alerts; the chat id is the default for schedules without their own |

Frontend (`nextjs-frontend/.env.local`, server-only): `BACKEND_API_URL` (required, no default;
`.env.example` sets `http://127.0.0.1:8000`) and `BACKEND_INTERNAL_KEY`. `AI_BASE_URL` must be
https. The scheduler also reads `WEB_CONCURRENCY` (set by some launchers) to warn about several workers.

#### Daily AI budget and rate limits

`POST /analyse` checks `AI_MAX_CALLS_PER_DAY` / `AI_MAX_COST_PER_DAY` against the day's stored
usage before each provider call. Cost is an estimate from a built-in price table (an unknown
model is charged the dearest known rate); treat it as a guard, not as billing.

- Cap reached: **429** with `Retry-After` (seconds to UTC midnight). Hits already analysed are
  served from the database without a call, so they work even then.
- Invalid cap (for example `AI_MAX_CALLS_PER_DAY=abc`): **503**, never silently unlimited. The API
  reads caps per `/analyse` request; the scheduler reads them once at startup, so restart after a
  change (an invalid value stops startup when the scheduler is on).
- Endpoint rate limits (`/scan`, `/analyse`): **429** with `Retry-After`. The window is in
  process memory and global to the endpoint, not per client.
- Startup logs a warning when neither cap is set, or when the API looks reachable beyond
  loopback without `SMC_INTERNAL_KEY`.

#### Scheduler (opt-in)

Set `SMC_SCHEDULER=1` to run saved schedules inside the API process (off by default, so
tests and local runs start no threads). A schedule has a frequency of `15m`, `1h`, `4h` or `1d`
and runs just after each candle **closes** (5 s grace): 15m and 1h on the UTC grid, 4h and 1d on
the broker's wall clock, so set `SMC_SERVER_TZ` for those. A scheduled run scans closed bars,
analyses hits (same caps and cache as `/analyse`), applies the delivery rules and sends to
Telegram. After downtime it runs once and rejoins the grid; missed slots are not replayed.
Scheduled scans share the `/scan` lock. Run a single uvicorn worker (no `--workers N`), or
every worker would scan and alert.

Delivery rules, in order: HOLD is not sent unless `send_hold`; verdicts below `min_confidence`
are skipped; with `only_on_change` a verdict equal to the previous action for that symbol and
timeframe is skipped. A schedule's `min_score` picks which hits go to the AI.

#### Telegram alerts

Create a bot with @BotFather, put its token in `TELEGRAM_BOT_TOKEN`, message the bot (or add it
to a group) and put the chat id (a number, or `@channelname`) in `TELEGRAM_CHAT_ID` or on each
schedule. Check it with `POST /telegram/test`. Every message ends with "Advisory only - no
orders are placed."

Alerts are **at-most-once** per schedule, symbol, timeframe, zone and bar: a claim is written
before the send. A send that fails releases its claim and is retried by a later run; if the
process dies between claim and send, that alert is lost and not retried. The token never appears
in responses or logs.

## Web page (`nextjs-frontend/`)

A Next.js 16 page at `/scan` that runs the same scan through the API and shows the rows with
status and bias pills, score pips, the skipped symbols, an auto-rescan (`?every=N` minutes)
and a CSV download (`/scan/export`, same columns as the CLI). The form is a GET form, so every
scan has a shareable URL and the page works without JavaScript.

```bash
cd nextjs-frontend && npm install && cp .env.example .env.local
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

### AI analysis from the CLI

`--ai` analyses the hits after the scan and adds `ai_action`, `ai_confidence`, `ai_entry`,
`ai_stop`, `ai_target` and `ai_note` columns to the table and the CSV (the columns are absent
without `--ai`). Verdicts are advisory only; nothing places an order.

```bash
uv run smc-scan --demo --ai --ai-provider fake --ai-min-score 0   # offline demo, no key
uv run smc-scan --source mt5 --tf 1h --ai --ai-min-score 3 --ai-max 3
```

- `--ai-provider`: `claude` (default; needs `ANTHROPIC_API_KEY`, optional `AI_MODEL`) or `fake`
  (canned HOLD replies, only with `--demo`). `--ai-min-score` (0-4, default 2) and `--ai-max`
  (1-50, default 5) limit which rows are sent and how many per run.
- Verdicts are stored in SQLite at `SMC_DB_PATH` (default `./smc.db`, git-ignored). A bar that
  already has a verdict is not sent again, so `--every N` pays only for new bars.
- An AI problem (missing key, provider error, database error) never hides the scan: the table
  and CSV are still written and the affected rows carry a short note.

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

The scan uses **closed bars only**: the still-forming candle is dropped, so TOUCHING/NEAR and
the price do not change between scans of the same bar. Pass `--include-forming` to the CLI to
scan the live candle instead (the API is always closed-only). A bar counts as closed once the
symbol's last tick time is past its end, so after a market close or on a quiet symbol the
newest closed bar can be skipped until the next tick. A warning is logged when the last bar is more than two timeframes behind
the symbol's last tick (closed market or dead feed).

### CSV

Header `time,open,high,low,close[,volume]`, ISO-8601 times, any order (sorted on load). Years of
history per timeframe can be built from Dukascopy tick exports with `smc-resample-ticks`; see
[docs/data.md](docs/data.md).

### Backtest

`smc-backtest` replays strategies bar by bar, walks them forward (in-sample vs out-of-sample,
against random-entry and direction-flipped baselines) and prints one table with a verdict:

```bash
uv run smc-backtest --source csv --symbols data/GBPUSD_1h.csv --tf 1h --bars 5000 --stride 5 --strategy smc-default --out backtests --save
```

`--out` writes one CSV of per-signal rows per strategy and `summary.json`; `--save` stores the
summaries in `SMC_DB_PATH`, where `GET /backtests` lists them. With csv files the spread
defaults to the mean `spread` column. A run at stride 1 over 5000 bars takes minutes per
symbol; `--stride` trades precision for speed.

## Quick start (no terminal, no key)

```bash
uv sync
uv run smc-scan --demo --ai --ai-provider fake --ai-min-score 0      # CLI: scan + canned verdicts
uv run uvicorn smc_scanner.api:app --host 127.0.0.1 --port 8000      # terminal 1
cd nextjs-frontend && npm install && cp .env.example .env.local     # once
npm run dev                                                           # terminal 2
```

Open http://localhost:3000/scan and pick the `demo` source. The `fake` provider is CLI/demo-only;
the API, scheduler and web app use only `claude`, so AI verdicts there need `ANTHROPIC_API_KEY`.
Scheduled runs analyse hits and fail without it. To try a schedule, add `SMC_SCHEDULER=1` and the
key to `.env`, then create a schedule with `"source": "demo"` (source has no default).

## How verdicts are produced, and their limits

Each hit at or above the minimum score is turned into a JSON context of already-computed scanner
numbers (never a chart image) and sent to Claude with a fixed prompt (`smc-verdict-1`). The reply
must be one JSON object: `BUY`, `SELL` or `HOLD`, a confidence, entry, stop, up to three targets,
a quality grade and short reasons. Replies are untrusted: anything malformed or implausible
(stop outside 0.1-5 ATR of entry, targets beyond 15 ATR, reward/risk outside 1-20) becomes a
**HOLD flagged as downgraded** with the reason, and risk/reward is always recomputed locally.
An entry more than 1.5 ATR from the zone is downgraded too. One verdict is stored per symbol,
timeframe, zone and bar, so a successfully analysed bar is not paid for twice (a new prompt or
model does not re-analyse old bars). A failed call is counted at worst-case cost and retried
after a cooldown, up to 3 attempts per bar.

The verdict is **advisory only**. The model sees the scanner's numbers and nothing else (no news,
spreads, sessions or account state), can be wrong, and nothing in this repository places or
manages an order. Verdict text is model-controlled: it is cleaned of control characters but must
be escaped by whatever renders it.

## Known limits

- The CLI `--ai` path is **not wired to the daily caps**: `AI_MAX_CALLS_PER_DAY` and
  `AI_MAX_COST_PER_DAY` apply to `POST /analyse` and the scheduler only. Use `--ai-max` there.
- If the cap is reached **part-way through** an `/analyse` run, the response is a 429 and the rows
  already analysed are not in it; they are stored, so read them from `GET /analyses`.
- The rate limiters, the scan lock and the scheduler guard live in one process. Run a single
  uvicorn worker. The limit is global per endpoint, not per client.
- **Auth fails open**: with `SMC_INTERNAL_KEY` unset the API accepts any caller that passes the
  `Host` check. Set it before binding beyond loopback (startup warns when it can tell).
- Scans use closed bars only; after a market close the newest closed bar may be skipped until the
  next tick (see MetaTrader 5 above). Telegram alerts are at-most-once (see above).

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Web page says the scanner is unreachable | API not running or `BACKEND_API_URL` wrong; start uvicorn on `127.0.0.1:8000` |
| 400 "Invalid host header" (plain text) | `Host` header not in `SMC_API_ALLOWED_HOSTS` |
| 401 from the API | `BACKEND_INTERNAL_KEY` differs from `SMC_INTERNAL_KEY` |
| Web page says "The scanner API could not be reached" | API not running, or no `nextjs-frontend/.env.local` (`BACKEND_API_URL` unset); copy `.env.example` and restart `npm run dev` |
| 503 "No symbol could be loaded" / CLI exit code 1 | MT5 terminal closed or not logged in; log in, or set `MT5_*` |
| Symbols skipped as unknown | broker suffixes (`.p`, `.r`, `m`); write them as Market Watch shows them in `watchlist.yaml` |
| 503 "AI analysis is disabled" | `ANTHROPIC_API_KEY` not set (an invalid `AI_MODEL`, `AI_BASE_URL` or timeout says "unavailable"; provider call failures are 502 "AI provider failed"; scheduled failures show only in the job log) |
| 503 "AI budget settings are invalid" | `AI_MAX_CALLS_PER_DAY` / `AI_MAX_COST_PER_DAY` not valid (calls: whole number, cost: decimal, both 0 or more) |
| 429 on `/analyse` | rate limit or daily cap; wait for `Retry-After` |
| Schedules never run | `SMC_SCHEDULER` not set. 4h/1d runs hours off: set `SMC_SERVER_TZ`. Duplicate scans or alerts: several workers |
| 503 on `/telegram/test` | `TELEGRAM_BOT_TOKEN` not set |

## Module map (for contributors)

| Area | Modules |
|---|---|
| Scan engine | `scanner.py`, `structure.py`, `zones.py`, `scoring.py`, `smc_lib.py`, `models.py`, `report.py` |
| Data sources | `loaders/` (`mt5.py`, `csv_loader.py`, `demo.py`), `watchlist.py` |
| Data preparation | `data/resample_ticks.py` (`smc-resample-ticks`, tick export to candle CSVs) |
| CLI | `cli.py`, `ai_cli.py` |
| AI verdicts | `ai/` (`prompt.py`, `context.py`, `providers.py`, `verdict.py`, `analyst.py`, `store.py`, `budget.py`) |
| Shared | `config.py`, `ratelimit.py` (API rate limiter) |
| Scheduler | `schedule/` (`timing.py`, `rules.py`, `store.py`, `joblog.py`, `runner.py`) |
| Backtest | `backtest/` (`replay.py`, `outcome.py`, `stats.py`, `report.py`, `baseline.py`, `walkforward.py`, `sweep.py`, `store.py`, `jobs.py`, `cli.py` for `smc-backtest`) |
| Telegram | `notify/telegram.py` |
| HTTP API | `api/`, `openapi_export.py` |
| Web | `nextjs-frontend/src/app` (`/scan`, `/analyses/[id]`, dashboard at the root page), `src/lib/api` |

Story history lives in Jira (project TRAD): e.g. TRAD-13 job log, TRAD-14 schedule API,
TRAD-17 analysis detail page, TRAD-19 scan-page verdicts, TRAD-22 budget guard and wiring.

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
