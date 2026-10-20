import { describe, expect, it } from 'vitest';
import { analysesCsvFileName, analysesToCsv } from '@/components/analyses/history/csv';
import { makeAnalysis } from '../../helpers/fixtures';

describe('analysesToCsv', () => {
  it('writes a header and one CRLF line per analysis', () => {
    const csv = analysesToCsv([
      makeAnalysis({ id: 7, verdict: { action: 'BUY', confidence: 72, quality: 'A' } }),
    ]);
    const [header, line] = csv.split('\r\n');
    expect(header).toBe('id,time,symbol,tf,action,confidence,quality,zone,provider');
    expect(line).toBe('7,2026-10-19T23:05:00Z,EURUSD,1h,BUY,72,A,bull FVG,anthropic');
    expect(csv.endsWith('\r\n')).toBe(true);
  });

  it('leaves verdict cells empty for a failed analysis', () => {
    const csv = analysesToCsv([makeAnalysis({ verdict: null, status: 'failed' })]);
    expect(csv.split('\r\n')[1]).toBe('1,2026-10-19T23:05:00Z,EURUSD,1h,,,,bull FVG,anthropic');
  });

  it('neutralises formula prefixes and quotes special characters', () => {
    const csv = analysesToCsv([
      makeAnalysis({ symbol: '=HYPERLINK("x")', zone: '+1,5', provider: '@cmd' }),
    ]);
    const line = csv.split('\r\n')[1];
    expect(line).toContain(`"'=HYPERLINK(""x"")"`);
    expect(line).toContain(`"'+1,5"`);
    expect(line).toContain(`'@cmd`);
  });
});

describe('analysesToCsv hardening', () => {
  it('guards a formula behind leading whitespace', () => {
    const csv = analysesToCsv([makeAnalysis({ zone: '  =1+1' })]);
    expect(csv).toContain(`'  =1+1`);
  });

  it('does not throw on a non-string field from the API', () => {
    const odd = makeAnalysis({ zone: ['a', 'b'] as unknown as string });
    expect(() => analysesToCsv([odd])).not.toThrow();
  });
});

describe('analysesCsvFileName', () => {
  it('stamps the file with the UTC time', () => {
    expect(analysesCsvFileName(new Date('2026-10-20T12:30:05.123Z'))).toBe(
      'smc-analyses-20261020T123005Z.csv'
    );
  });
});
