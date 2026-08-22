/**
 * Pure math for lightbox touch gestures (pinch zoom). Kept separate from
 * the DOM wiring so it's unit-testable - real gestures are device territory.
 */
import { LIGHTBOX_ZOOM_MAX_SCALE } from '../config';

export interface Point {
  x: number;
  y: number;
}

export function pointerDistance(a: Point, b: Point): number {
  return Math.hypot(b.x - a.x, b.y - a.y);
}

export function pointerMidpoint(a: Point, b: Point): Point {
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
}

/**
 * Target scale for a pinch: the scale at gesture start times the ratio of
 * the current finger distance to the starting distance, clamped to
 * [1, LIGHTBOX_ZOOM_MAX_SCALE]. A degenerate zero start distance keeps the
 * starting scale.
 */
export function computePinchScale(
  startScale: number,
  startDistance: number,
  currentDistance: number
): number {
  if (startDistance <= 0) return startScale;
  const raw = startScale * (currentDistance / startDistance);
  return Math.min(LIGHTBOX_ZOOM_MAX_SCALE, Math.max(1, raw));
}
