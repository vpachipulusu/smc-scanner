import type { CumulativePoint } from './stats';

/** Pure geometry for the equity curve: no React, no DOM. */

/** Above this many points the curve is thinned; the drawing gains nothing from more. */
export const MAX_CURVE_POINTS = 500;

export type CurveBox = { width: number; height: number; padding: number };

export type CurvePoint = { x: number; y: number; point: CumulativePoint };

export type EquityGeometry = {
  points: CurvePoint[];
  /** `M x y L x y ...`, empty without points. */
  path: string;
  /** Where cumulative R is zero. */
  baselineY: number;
};

/**
 * At most `max` points, always keeping the first, the last and the lowest and highest value, in
 * their original order.
 */
export function downsample(
  points: readonly CumulativePoint[],
  max: number = MAX_CURVE_POINTS
): CumulativePoint[] {
  if (points.length <= max) return [...points];
  let low = 0;
  let high = 0;
  points.forEach((p, i) => {
    if (p.cumulative_r < points[low].cumulative_r) low = i;
    if (p.cumulative_r > points[high].cumulative_r) high = i;
  });
  const keep = new Set([0, points.length - 1, low, high]);
  const slots = Math.max(max - keep.size, 0);
  const stride = (points.length - 1) / (slots + 1);
  for (let step = 1; step <= slots && keep.size < max; step += 1) {
    keep.add(Math.round(step * stride));
  }
  return [...keep].sort((a, b) => a - b).map((i) => points[i]);
}

const round = (value: number): number => Math.round(value * 100) / 100;

/** Maps points into the box. Zero is always inside the range so the baseline can be drawn. */
export function equityGeometry(points: readonly CumulativePoint[], box: CurveBox): EquityGeometry {
  const finite = points.filter((p) => Number.isFinite(p.cumulative_r));
  const values = finite.map((p) => p.cumulative_r);
  let top = Math.max(0, ...values);
  let bottom = Math.min(0, ...values);
  if (top === bottom) {
    top = 1;
    bottom = -1;
  }
  const innerHeight = box.height - 2 * box.padding;
  const innerWidth = box.width - 2 * box.padding;
  const yOf = (value: number): number =>
    round(box.padding + ((top - value) / (top - bottom)) * innerHeight);
  const xOf = (index: number): number =>
    finite.length === 1
      ? box.width / 2
      : round(box.padding + (index / (finite.length - 1)) * innerWidth);

  const curve = finite.map((point, index) => ({
    x: xOf(index),
    y: yOf(point.cumulative_r),
    point,
  }));
  const path = curve.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x} ${p.y}`).join('');
  return { points: curve, path, baselineY: yOf(0) };
}
