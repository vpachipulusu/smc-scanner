// Deterministic stand-in for the scanner API, used only by the Playwright suite. It speaks the
// subset of openapi.json the frontend calls, keeps its state in memory and never touches MT5, a
// database or an AI provider: the "fake provider" verdicts below are canned. `POST /__reset`
// restores the seed so every test starts from the same state.
import http from 'node:http';

const PORT = Number(process.env.E2E_API_PORT);
if (!Number.isInteger(PORT) || PORT <= 0) throw new Error('E2E_API_PORT is not set');
const INTERNAL_KEY = process.env.E2E_INTERNAL_KEY;
if (!INTERNAL_KEY) throw new Error('E2E_INTERNAL_KEY is not set');

const ROWS = [
  {
    instrument: 'EURUSD',
    status: 'TOUCHING',
    zone: 'bullish OB',
    zone_low: 1.0821,
    zone_high: 1.0834,
    price: 1.0828,
    dist_atr: 0,
    bias: 'bullish',
    in_ote: true,
    trendline_ok: true,
    ob_fvg: true,
    score: 4,
    zone_age: 12,
    prior_touches: 0,
    bar_time: '2026-10-20 10:00',
  },
  {
    instrument: 'XAUUSD',
    status: 'NEAR',
    zone: 'bearish FVG',
    zone_low: 2651.2,
    zone_high: 2655.8,
    price: 2649.9,
    dist_atr: 0.3,
    bias: 'bearish',
    in_ote: false,
    trendline_ok: true,
    ob_fvg: false,
    score: 3,
    zone_age: 5,
    prior_touches: 1,
    bar_time: '2026-10-20 10:00',
  },
];

const VERDICTS = {
  EURUSD: {
    schema_version: 1,
    action: 'BUY',
    confidence: 82,
    quality: 'A',
    entry: 1.0828,
    stop: 1.0812,
    targets: [1.0856, 1.0882],
    risk_reward: 1.75,
    invalidation: 1.0812,
    reasons: ['Fresh bullish order block', 'Price inside the OTE band'],
    summary: 'Fake provider: long from the order block.',
    downgraded: false,
    downgrade_reason: null,
  },
  XAUUSD: {
    schema_version: 1,
    action: 'SELL',
    confidence: 64,
    quality: 'B',
    entry: 2650.5,
    stop: 2659,
    targets: [2635],
    risk_reward: 1.8,
    invalidation: 2659,
    reasons: ['Bearish fair value gap overhead'],
    summary: 'Fake provider: short into the gap.',
    downgraded: false,
    downgrade_reason: null,
  },
};

function makeAnalysis(id, symbol, verdict, createdAt) {
  return {
    id,
    created_at: createdAt,
    symbol,
    tf: '1h',
    zone_kind: verdict?.action === 'SELL' ? 'fvg' : 'ob',
    zone: verdict?.action === 'SELL' ? 'bearish FVG' : 'bullish OB',
    zone_low: 1.08,
    zone_high: 1.09,
    bar_time: createdAt,
    provider: 'fake',
    model: 'fake-1',
    prompt_version: 'v1',
    attempts: 1,
    status: verdict ? 'ok' : 'failed',
    verdict,
  };
}

const SEED_ANALYSES = [
  makeAnalysis(3, 'XAUUSD', VERDICTS.XAUUSD, '2026-10-20T09:00:00Z'),
  makeAnalysis(
    2,
    'EURUSD',
    { ...VERDICTS.EURUSD, action: 'HOLD', confidence: 40 },
    '2026-10-20T08:00:00Z'
  ),
  makeAnalysis(1, 'EURUSD', VERDICTS.EURUSD, '2026-10-20T07:00:00Z'),
];

const clone = (value) => JSON.parse(JSON.stringify(value));

let analyses;
let schedules;
let logs;
let nextId;

function reset() {
  analyses = clone(SEED_ANALYSES);
  schedules = [];
  logs = [];
  nextId = { analysis: 4, schedule: 1, log: 1 };
}
reset();

function send(res, status, body) {
  res.writeHead(status, { 'content-type': 'application/json' });
  res.end(JSON.stringify(body));
}

const fail = (res, status, error) => send(res, status, { success: false, error });

function readBody(req) {
  return new Promise((resolve) => {
    let raw = '';
    req.on('error', () => resolve(null));
    req.on('data', (chunk) => (raw += chunk));
    req.on('end', () => {
      try {
        const parsed = raw ? JSON.parse(raw) : {};
        resolve(typeof parsed === 'object' && parsed !== null ? parsed : null);
      } catch {
        resolve(null);
      }
    });
  });
}

function scheduleOut(body, id) {
  return {
    id,
    name: body.name,
    source: body.source,
    tf: body.tf,
    symbols: body.symbols,
    frequency: body.frequency,
    min_score: body.min_score ?? 2,
    min_confidence: body.min_confidence ?? 0,
    only_on_change: body.only_on_change ?? false,
    send_hold: body.send_hold ?? false,
    enabled: body.enabled ?? true,
    telegram_chat_id: body.telegram_chat_id ?? null,
    last_run_at: null,
    next_run_at: null,
  };
}

function filterAnalyses(url) {
  const symbol = url.searchParams.get('symbol');
  const action = url.searchParams.get('action');
  const minConfidence = Number(url.searchParams.get('min_confidence') ?? 0);
  return analyses.filter(
    (a) =>
      (!symbol || a.symbol === symbol) &&
      (!action || a.verdict?.action === action) &&
      (a.verdict?.confidence ?? 0) >= minConfidence
  );
}

async function handleSchedule(req, res, id, suffix) {
  const index = schedules.findIndex((s) => s.id === id);
  if (index === -1) return fail(res, 404, 'Schedule not found');
  const { method } = req;

  if (!suffix && method === 'GET') return send(res, 200, schedules[index]);
  if (!suffix && method === 'PATCH') {
    const body = await readBody(req);
    if (body === null) return fail(res, 422, 'Invalid body');
    schedules[index] = { ...schedules[index], ...body, id };
    return send(res, 200, schedules[index]);
  }
  if (!suffix && method === 'DELETE') {
    schedules.splice(index, 1);
    logs = logs.filter((l) => l.schedule_id !== id);
    return send(res, 200, { deleted: true });
  }
  if (suffix === '/run' && method === 'POST') {
    logs.unshift({
      id: nextId.log++,
      schedule_id: id,
      started_at: '2026-10-20T11:00:00Z',
      finished_at: '2026-10-20T11:00:01Z',
      duration_ms: 1000,
      status: 'success',
      hits: ROWS.length,
      delivered: 0,
      skipped: ROWS.length,
      skip_reason: 'telegram disabled',
      error: null,
    });
    return send(res, 200, {
      status: 'ok',
      rows: ROWS.length,
      delivered: 0,
      skipped: ROWS.length,
      error_count: 0,
    });
  }
  if (suffix === '/logs' && method === 'GET') {
    return send(res, 200, { items: logs.filter((l) => l.schedule_id === id), next_cursor: null });
  }
  return fail(res, 404, 'Not found');
}

async function route(req, res) {
  const url = new URL(req.url, 'http://stub');
  const { pathname: path } = url;
  const { method } = req;

  if (path === '/health') return send(res, 200, { status: 'ok', version: 'e2e' });
  // Same contract as the real API: every other route needs the shared key.
  if (req.headers['x-internal-key'] !== INTERNAL_KEY) {
    return fail(res, 401, 'Invalid internal key');
  }

  if (path === '/__reset' && method === 'POST') {
    reset();
    return send(res, 200, { reset: true });
  }

  if (path === '/config' && method === 'GET') {
    return send(res, 200, {
      sources: ['mt5', 'demo'],
      timeframes: ['5m', '15m', '30m', '1h', '4h', '1d'],
      defaults: { source: 'mt5', tf: '1h', bars: 500, swing: 10, near: 0.5 },
      limits: { min_bars: 15, max_bars: 5000, max_swing: 100, max_near: 5, max_symbols: 50 },
      watchlist: { mt5: ['EURUSD', 'XAUUSD'], demo: ['EURUSD', 'XAUUSD'] },
    });
  }

  if (path === '/scan' && method === 'GET') {
    return send(res, 200, {
      source: url.searchParams.get('source') ?? 'mt5',
      tf: url.searchParams.get('tf') ?? '1h',
      count: ROWS.length,
      rows: ROWS,
      failures: [],
    });
  }

  if (path === '/analyse' && method === 'POST') {
    const body = await readBody(req);
    if (body === null) return fail(res, 422, 'Invalid body');
    const rows = ROWS.map((row) => ({
      ...row,
      ai: { status: 'analysed', verdict: VERDICTS[row.instrument], note: 'fake provider' },
    }));
    for (const row of rows) {
      analyses.unshift(
        makeAnalysis(nextId.analysis++, row.instrument, row.ai.verdict, '2026-10-20T11:00:00Z')
      );
    }
    return send(res, 200, {
      source: body.source ?? 'mt5',
      tf: body.tf ?? '1h',
      count: rows.length,
      rows,
      failures: [],
    });
  }

  if (path === '/analyses' && method === 'GET') {
    const limit = Math.max(0, Number(url.searchParams.get('limit')) || 25);
    return send(res, 200, { items: filterAnalyses(url).slice(0, limit), next_cursor: null });
  }

  const analysisMatch = path.match(/^\/analyses\/(\d+)$/);
  if (analysisMatch && method === 'GET') {
    const found = analyses.find((a) => a.id === Number(analysisMatch[1]));
    return found ? send(res, 200, found) : fail(res, 404, 'Analysis not found');
  }

  if (path === '/schedules' && method === 'GET') return send(res, 200, { items: schedules });
  if (path === '/schedules' && method === 'POST') {
    const body = await readBody(req);
    if (body === null || !body.name || !Array.isArray(body.symbols)) {
      return fail(res, 422, 'Invalid body');
    }
    const created = scheduleOut(body, nextId.schedule++);
    schedules.push(created);
    return send(res, 201, created);
  }

  const scheduleMatch = path.match(/^\/schedules\/(\d+)(\/run|\/logs)?$/);
  if (scheduleMatch) return handleSchedule(req, res, Number(scheduleMatch[1]), scheduleMatch[2]);

  return fail(res, 404, 'Not found');
}

const server = http.createServer((req, res) => {
  route(req, res).catch(() => {
    if (!res.headersSent) fail(res, 500, 'Stub failure');
  });
});
server.on('error', (error) => {
  console.error(error);
  process.exit(1);
});
server.listen(PORT, '127.0.0.1');
