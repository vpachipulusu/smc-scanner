import {
  downsample,
  equityGeometry,
  type CurveBox,
  type EquityGeometry,
} from '@/lib/journal/equity';
import type { CumulativePoint } from '@/lib/journal/stats';

/**
 * Cumulative R after each closed backtest trade, drawn with the journal's curve geometry. The API
 * stores only summary statistics, so per-trade R comes from a CLI export (`--out`); without it
 * there is no curve.
 */

/** Each trade's R and the running total, in trade order. Non-finite R values are skipped. */
export function cumulativeTrades(rs: readonly number[]): CumulativePoint[] {
  let total = 0;
  return rs.filter(Number.isFinite).map((r, index) => {
    total += r;
    return {
      entry_id: index + 1,
      closed_at: '',
      r,
      cumulative_r: Math.round(total * 1e6) / 1e6,
    };
  });
}

/** The curve's points (thinned to the journal's maximum) mapped into the box. */
export function tradeCurve(rs: readonly number[], box: CurveBox): EquityGeometry {
  return equityGeometry(downsample(cumulativeTrades(rs)), box);
}
