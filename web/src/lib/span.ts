import type { Span } from "../types";

export type { Span };
export const MIN_SPAN = 0.1;

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max);

export function clampSpan(s: Span, duration: number): Span {
  const start = clamp(s.start, 0, Math.max(0, duration - MIN_SPAN));
  return { start, end: clamp(s.end, start + MIN_SPAN, Math.max(duration, start + MIN_SPAN)) };
}

// A move keeps the length and stops at both ends of the video.
export function moveSpan(s: Span, delta: number, duration: number): Span {
  const length = s.end - s.start;
  const start = clamp(s.start + delta, 0, Math.max(0, duration - length));
  return { start, end: start + length };
}

// A resize keeps the other edge and at least MIN_SPAN of length.
export function resizeSpan(s: Span, edge: "start" | "end", delta: number, duration: number): Span {
  return edge === "start"
    ? { start: clamp(s.start + delta, 0, s.end - MIN_SPAN), end: s.end }
    : { start: s.start, end: clamp(s.end + delta, s.start + MIN_SPAN, duration) };
}
