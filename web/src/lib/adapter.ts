import type { FilterResult, Job, Source, SourceKind, SourceStatus } from "../types";
import { objectColor } from "./selection";

export interface SpanBox { id: string; start: number; end: number }

export interface TrackRow {
  id: string;
  name: string;
  description: string;
  kind: SourceKind;
  origin: "separated" | "generated";
  status: SourceStatus;
  keep: boolean;
  gain: number;
  pitch: number;
  trackPath: string | null;
  spans: SpanBox[];
  spansEditable: boolean;
  pairOf: string | null;
  filter: FilterResult | null;
  attempts: number;
  // The failed step's message for a failed source, else null.
  failure: string | null;
  color: string;
}

export interface ResidualRow { path: string; keep: boolean; gain: number }

export interface JobView {
  rows: TrackRow[];
  residual: ResidualRow | null;
  skipped: Source[];
  duration: number;
}

// A generated replacement sits right after the source it replaces; both carry `pairOf`.
function ordered(shown: Source[]): Source[] {
  const present = new Set(shown.map((s) => s.id));
  const result: Source[] = [];
  for (const s of shown) {
    if (s.replaces && present.has(s.replaces)) continue;
    result.push(s, ...shown.filter((g) => g.replaces === s.id));
  }
  return result;
}

export function jobToView(job: Job): JobView {
  const shown = job.sources.filter((s) => s.status !== "skipped");
  const rows = ordered(shown).map((s, i): TrackRow => {
    const pair = s.replaces ?? shown.find((g) => g.replaces === s.id)?.id ?? null;
    return {
      id: s.id,
      name: s.plan.name,
      description: s.plan.description,
      kind: s.plan.kind,
      origin: s.origin,
      status: s.status,
      keep: s.keep,
      gain: s.gain,
      pitch: s.pitch_semitones,
      trackPath: s.track_path,
      spans: s.plan.spans.map((span, n) => ({ id: `${s.id}#${n}`, start: span.start, end: span.end })),
      // The generator does not use spans; a silent video has no audio to re-separate.
      spansEditable: s.origin === "separated" && !job.silent,
      pairOf: pair && shown.some((t) => t.id === pair) ? pair : null,
      filter: s.filter,
      attempts: s.attempts,
      failure: s.status === "failed" ? (job.steps.find((t) => t.status === "failed" && t.key.endsWith(`:${s.id}`))?.message ?? null) : null,
      color: objectColor(i),
    };
  });
  const { path, keep, gain } = job.residual;
  return {
    rows,
    residual: path ? { path, keep, gain } : null,
    skipped: job.sources.filter((s) => s.status === "skipped"),
    duration: job.duration,
  };
}
