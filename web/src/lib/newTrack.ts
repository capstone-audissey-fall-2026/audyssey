import type { Command, Job, Method, SourceKind, Span } from "../types";

export const NEW_TRACK_KINDS: SourceKind[] = ["sfx", "ambience", "music", "dialogue"];
export const METHOD_LABEL: Record<Method, string> = { separate: "Separate (SAM Audio)", generate: "Generate (internal model)" };

export interface NewTrackForm { name: string; kind: SourceKind; description: string; method: Method }

// Draft span of a new track: 2 s from the playhead, kept inside the video.
export function newTrackSpan(time: number, duration: number): Span {
  const start = Math.min(Math.max(time, 0), Math.max(duration - 0.1, 0));
  return { start, end: Math.min(start + 2, duration) };
}

// A job started with Generate (or a silent video) opens the form on Generate.
export const defaultNewTrackMethod = (job: Job): Method => (job.method === "generate" || job.silent ? "generate" : "separate");

// A silent video can only generate; speech is never generated.
export function newTrackCommand(form: NewTrackForm, spans: Span[], job: Job): Command {
  const method: Method = job.silent ? "generate" : form.method;
  if (form.kind === "dialogue" && method === "generate") throw new Error("Speech is not generated.");
  return {
    type: "add_source",
    method,
    plan: { name: form.name.trim(), kind: form.kind, description: form.description.trim(), spans, visual_hint: null },
  };
}
