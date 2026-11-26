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

// A drag shorter than MIN_SPAN draws nothing.
export function drawSpan(spans: Span[], from: number, to: number, duration: number): Span[] {
  const start = clamp(Math.min(from, to), 0, duration);
  const end = clamp(Math.max(from, to), 0, duration);
  return end - start < MIN_SPAN ? spans : [...spans, { start, end }];
}

// A source keeps at least one span: removing the last one returns the list unchanged.
export function removeSpan(spans: Span[], index: number): Span[] {
  return spans.length <= 1 ? spans : spans.filter((_, i) => i !== index);
}

export function sortSpans(spans: Span[]): Span[] {
  return [...spans].sort((a, b) => a.start - b.start || a.end - b.end);
}

export function formatSpan(span: Span): string {
  return `${span.start.toFixed(1)}–${span.end.toFixed(1)} s`;
}
