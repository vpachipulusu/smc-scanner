/** The download must match the CLI's scan_results.csv: columns, order, True/False, quoting. */
import { describe, expect, it } from 'vitest';
import { CSV_COLUMNS, csvFileName, rowsToCsv } from '@/lib/scan/csv';
import { makeRow } from '../../helpers/fixtures';

describe('rowsToCsv', () => {
  it('writes the header in the CLI column order', () => {
    expect(rowsToCsv([]).split('\r\n')[0]).toBe(
      'instrument,status,zone,zone_low,zone_high,price,dist_atr,bias,in_ote,trendline_ok,ob_fvg,score,zone_age,prior_touches,bar_time'
    );
    expect(CSV_COLUMNS).toHaveLength(15);
  });

  it('spells booleans like Python and ends lines with CRLF', () => {
    const csv = rowsToCsv([makeRow()]);

    expect(csv).toBe(
      'instrument,status,zone,zone_low,zone_high,price,dist_atr,bias,in_ote,trendline_ok,ob_fvg,score,zone_age,prior_touches,bar_time\r\n' +
        'EURUSD,TOUCHING,bull FVG,1.0971,1.09898,1.09988,0,bearish,False,True,False,1,2,0,2026-10-19 23:00:00\r\n'
    );
  });

  it('quotes cells with commas, quotes or newlines', () => {
    const csv = rowsToCsv([makeRow({ instrument: 'A,B', zone: 'say "hi"' })]);

    expect(csv).toContain('"A,B",TOUCHING,"say ""hi"""');
  });

  it('neutralises spreadsheet formulas', () => {
    const csv = rowsToCsv([makeRow({ instrument: '=HYPERLINK("x")', zone: '+1', bar_time: '-x' })]);

    expect(csv).toContain(`"'=HYPERLINK(""x"")",TOUCHING,'+1`);
    expect(csv.trimEnd().endsWith(",'-x")).toBe(true);
  });

  it('leaves negative numbers alone', () => {
    expect(rowsToCsv([makeRow({ dist_atr: -0.25, zone_low: -1 })])).toContain(
      ',-1,1.09898,1.09988,-0.25,'
    );
  });
});

describe('csvFileName', () => {
  it('stamps the source, timeframe and UTC time', () => {
    expect(csvFileName('demo', '1h', new Date('2026-10-20T01:02:03.456Z'))).toBe(
      'smc-scan-demo-1h-20261020T010203Z.csv'
    );
  });
});
