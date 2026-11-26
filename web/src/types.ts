// Mirrors src/audyssey/contracts.py. Times are seconds.

export interface Span { start: number; end: number }

export interface VisualHint {
  time: number;
  box: [number, number, number, number]; // x0, y0, x1, y1, normalized 0..1
  description: string;
}

export type SourceKind = "dialogue" | "sfx" | "music" | "ambience";

export interface SourcePlan {
  name: string;
  kind: SourceKind;
  description: string;
  spans: Span[];
  visual_hint: VisualHint | null;
}

export interface PlanIssue { source_name: string | null; kind: string; message: string }

export interface FilterResult {
  passed: boolean;
  scores: Record<string, number>;
  reason: string;
  suggestion: SourcePlan | null;
}

export type SourceStatus = "pending" | "running" | "done" | "failed" | "skipped";

export interface Source {
  id: string;
  plan: SourcePlan;
  origin: "separated" | "generated";
  replaces: string | null;
  track_path: string | null;
  filter: FilterResult | null;
  status: SourceStatus;
  attempts: number;
  keep: boolean;
  gain: number; // 0..2
  pitch_semitones: number; // -12..12
}

export interface Residual { path: string | null; keep: boolean; gain: number }

export interface StepStatus {
  key: string;
  status: "pending" | "running" | "done" | "failed" | "warning";
  round: number;
  max_rounds: number;
  message: string;
}

export interface RenderOutput { mix_wav: string; video_mp4: string; stems: string[] }

export type Method = "separate" | "generate";

export interface Job {
  id: string;
  video_path: string;
  silent: boolean;
  duration: number;
  audio_path: string;
  mono_path: string;
  peaks_path: string;
  sources: Source[];
  residual: Residual;
  plan_issues: PlanIssue[];
  steps: StepStatus[];
  outputs: RenderOutput | null;
  state: "new" | "running" | "ready" | "failed";
  method: Method | null;
  version: number;
  error: string | null;
}

export type Command =
  | { type: "keep"; source_id: string }
  | { type: "drop"; source_id: string }
  | { type: "set_gain"; source_id: string; gain: number }
  | { type: "set_pitch"; source_id: string; semitones: number }
  | { type: "reseparate"; source_id: string; description?: string | null; spans?: Span[] | null }
  | { type: "generate"; source_id: string; description?: string | null }
  | { type: "add_source"; plan: SourcePlan; method: Method }
  | { type: "render"; include_residual_stem: boolean };

export interface Clarify {
  type: "clarify";
  question: string;
  reason: "ambiguous_target" | "missing_value" | "composite" | "unsupported" | "other";
}

export type RouteDecision = Command | Clarify | { type: "none" };
export interface RouteResult { route_id: string; decision: RouteDecision }

// One item of GET /api/system: a server and the pipeline steps that run on it.
export interface Lane { id: string; name: string; models: string[]; steps: string[]; up: boolean | null }

// GET/POST /api/gpu-tools: the tools server the app uses. The token is never returned.
export interface GpuTools { tools_url: string; token_set: boolean; remote: Record<string, boolean> }

// One line of a job's trace.jsonl (GET /api/jobs/{id}/trace).
export interface TraceCall {
  id: string;
  step: string;
  tool: string;
  server: string;
  started: number;
  seconds: number;
  inputs: Record<string, unknown>;
  requests: Record<string, unknown>[];
  output: unknown;
  error: string | null;
}
