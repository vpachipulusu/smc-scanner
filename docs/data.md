# Historical candles from tick exports

`smc-resample-ticks` turns a Dukascopy tick export (Tick Data Suite) into one candle CSV per
timeframe that the `csv` source reads unchanged, so scans, schedules and backtests can use years
of history with a real spread per candle.

## The export

Tick Data Suite writes one zip per instrument, e.g. `GBPUSD_GMT+2_EU-DST.zip` (1.7 GB zipped,
12.9 GB / 318 million lines unzipped for 2003-2022). Each zip holds a single headerless CSV of
`timestamp,bid,ask` lines:

```text
2003.05.05 00:00:00.773,1.60377,1.60417
```

- Timestamps are `YYYY.MM.DD HH:MM:SS.mmm` in the **GMT+2 with EU daylight saving** broker clock
  (GMT+3 in European summer time), so a daily candle opens at 00:00 and closes at New York 5 pm,
  as on most MT4/MT5 servers.
- Prices drop trailing zeros (`1.6038` for `1.60380`); the precision is taken from the ticks.
- Dukascopy ticks carry no traded volume.

## The command

```bash
uv run smc-resample-ticks "C:\MainData\AlgoTrading\TDS Tick Data - 2022-11-12 Export\GBPUSD_GMT+2_EU-DST.zip" --out data --timeframes 1h,4h,1d
uv run smc-scan --source csv --tf 4h --symbols data/GBPUSD_4h.csv
```

| Option | Default | Meaning |
|---|---|---|
| `source` | | the `.zip` (its one CSV member is streamed, never extracted) or an extracted `.csv` |
| `--out DIR` | required | where `<SYMBOL>_<tf>.csv` files go; `data/` is git-ignored |
| `--symbol` | file name before the first `_` | output name: letters, digits, `.`, `_`, `-` |
| `--timeframes` | `5m,15m,30m,1h,4h,1d` | comma-separated, from the scanner's timeframes |
| `--price` | `mid` | `mid` = (bid + ask) / 2, or `bid` (MT4/MT5 charts show bid) |
| `--from YYYY-MM-DD` | everything | drop ticks before that day (file clock) |
| `--chunk-rows N` | 1,000,000 | ticks read per chunk; memory grows with it |
| `--force` | off | overwrite existing candle files (otherwise the run refuses) |

Output columns are `time,open,high,low,close,volume,spread`:

- `time` is the bar **open** in the file's clock (ISO, e.g. `2003-05-05T04:00:00`). No timezone
  conversion is done; 4h bars open at 00, 04, ... 20 and daily bars at 00:00 of that clock.
- `volume` is the **tick count** of the candle; `spread` the mean ask - bid of its ticks.
- `bid` prices keep the input's decimals; a `mid` keeps one more (the half point), and the spread
  two more.
- Gaps (weekends, holidays, feed outages) produce no candles; nothing is forward-filled.

## Behaviour

- The file is streamed chunk by chunk; only the still-open candle of each timeframe stays in
  memory and finished candles are appended to `<SYMBOL>_<tf>.csv.part` files, which are renamed
  into place when the run completes. A failed or interrupted run leaves no partial outputs.
- Progress is logged per chunk (lines read, current date). A malformed line (bad timestamp or
  price, a zero price or ask below bid, missing or extra fields, a blank line, or a tick older
  than one before it) is skipped and logged with its line number (the first 50); the total is
  reported at the end. The run exits 1 when more than 0.01% of lines were skipped; the candle
  files are still written so they can be inspected. A run already skipping ten times that rate
  after 100,000 lines stops early and writes nothing (one corrupt future timestamp would
  otherwise make every later tick "out of order").
- Existing candle files are never replaced without `--force`, and never when one of them is the
  input itself. Files are renamed one timeframe at a time, so a rename failing part-way (a file
  held open by another program) leaves the earlier timeframes new and the rest unchanged.

## Runtime

Measured on the GBPUSD export (318,578,661 ticks, 2003-05-05 to 2022-11-11, straight from the
zip) with `--timeframes 1h,4h,1d`: 7 min 14 s, peak working set 313 MiB at the default chunk
size, 0 lines skipped. That is about 1.4 s per million ticks; nearly all of it is parsing, so
more timeframes add little. Memory stays flat over the run and scales with `--chunk-rows`.

| File | Candles | Size |
|---|---|---|
| `GBPUSD_1h.csv` | 121,940 | 8.6 MB |
| `GBPUSD_4h.csv` | 30,556 | 2.2 MB |
| `GBPUSD_1d.csv` | 5,148 | 0.4 MB |

## Why per-timeframe files and no 1m

The CSV loader reads a whole file into memory and keeps the last `--bars` rows (`CsvLoader.load`;
`CsvLoader.read_all` returns every row), and the scanner asks for one timeframe at a time.
`--bars` is capped at 5000 (`MAX_BARS`) everywhere except `smc-backtest --lookback N`, which
replays up to 200,000 bars (`MAX_BACKTEST_BARS`) and, for csv files, defaults to the whole file
up to that cap: each replay step then scans only its last `N` bars, as a live scan with
`--bars N` would. One file per timeframe keeps each load small and needs no resampling at scan
time. A 1m file would be about 7 million rows (hundreds of MB) per 19-year
instrument and is not a scanner timeframe, so it is not produced; tick-level detail for backtest
exits is a later story.
