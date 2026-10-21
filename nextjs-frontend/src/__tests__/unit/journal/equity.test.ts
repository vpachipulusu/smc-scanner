import { describe, expect, it } from 'vitest';
import { MAX_CURVE_POINTS, downsample, equityGeometry } from '@/lib/journal/equity';
import type { CumulativePoint } from '@/lib/journal/stats';

const point = (i: number, cumulative_r: number): CumulativePoint => ({
  entry_id: i,
  closed_at: '2026-10-20T10:00:00Z',
  r: 1,
  cumulative_r,
});

const BOX = { width: 100, height: 50, padding: 5 };

describe('equityGeometry', () => {
  it('is empty without points', () => {
    expect(equityGeometry([], BOX)).toEqual({ points: [], path: '', baselineY: 25 });
  });

  it('scales values into the box and keeps y = 0 as a baseline', () => {
    const g = equityGeometry([point(1, 2), point(2, -2)], BOX);
    expect(g.points.map((p) => [p.x, p.y])).toEqual([
      [5, 5],
      [95, 45],
    ]);
    expect(g.baselineY).toBe(25);
    expect(g.path).toBe('M5 5L95 45');
  });

  it('includes zero in the range even when every value is positive', () => {
    const g = equityGeometry([point(1, 1), point(2, 2)], BOX);
    expect(g.baselineY).toBe(45);
    expect(g.points[1].y).toBe(5);
  });

  it('centres a single point', () => {
    const g = equityGeometry([point(1, 1)], BOX);
    expect(g.points[0].x).toBe(50);
    expect(g.path).toBe('M50 5');
  });

  it('draws a flat zero curve on the baseline instead of dividing by zero', () => {
    const g = equityGeometry([point(1, 0), point(2, 0)], BOX);
    expect(g.points.map((p) => p.y)).toEqual([g.baselineY, g.baselineY]);
  });

  it('drops points that are not finite', () => {
    const g = equityGeometry(
      [point(1, Number.NaN), point(2, 1), point(3, Number.POSITIVE_INFINITY)],
      BOX
    );
    expect(g.points).toHaveLength(1);
  });
});

describe('downsample', () => {
  it('returns short series untouched', () => {
    const pts = [point(1, 1), point(2, 2)];
    expect(downsample(pts)).toEqual(pts);
  });

  it('caps long series, keeping first, last, min and max in order', () => {
    const pts = Array.from({ length: 2000 }, (_, i) => point(i, Math.sin(i / 20) * 10));
    pts[777] = point(777, -50);
    pts[1234] = point(1234, 50);

    const out = downsample(pts);

    expect(out.length).toBeLessThanOrEqual(MAX_CURVE_POINTS);
    expect(out[0]).toBe(pts[0]);
    expect(out[out.length - 1]).toBe(pts[1999]);
    expect(out).toContain(pts[777]);
    expect(out).toContain(pts[1234]);
    const ids = out.map((p) => p.entry_id);
    expect(ids).toEqual([...ids].sort((a, b) => a - b));
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('honours a custom limit', () => {
    const pts = Array.from({ length: 50 }, (_, i) => point(i, i));
    expect(downsample(pts, 10).length).toBeLessThanOrEqual(10);
  });
});
