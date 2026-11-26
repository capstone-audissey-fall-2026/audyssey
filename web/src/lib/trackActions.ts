import type { Command, Job, Method, Span } from "../types";
import type { JobView, TrackRow } from "./adapter";
import type { EngineTrack } from "./audioEngine";
import { fileUrl } from "../api";

// The keep switch. Within a separated/generated pair only one plays, so turning one on turns the other off.
export function keepCommands(view: JobView, id: string, keep: boolean): Command[] {
  const commands: Command[] = [{ type: keep ? "keep" : "drop", source_id: id }];
  if (!keep || id === "residual") return commands;
  const row = view.rows.find((r) => r.id === id);
  const other = row?.pairOf ? view.rows.find((r) => r.id === row.pairOf) : undefined;
  if (other?.keep) commands.push({ type: "drop", source_id: other.id });
  return commands;
}

export type PrimaryAction = { label: string; command: Command } | { label: string; disabledReason: string };

// The selected track's main button for the chosen method. An edited description goes with the command.
export function primaryAction(
  row: TrackRow,
  method: Method,
  pendingSpans: Span[] | null,
  job: Job,
  description?: string,
): PrimaryAction {
  const text = description?.trim();
  const edited = text && text !== row.description ? { description: text } : {};
  if (method === "generate") {
    const label = row.origin === "generated" ? "Regenerate" : "Generate instead";
    if (row.kind === "dialogue") return { label, disabledReason: "Speech is not generated." };
    return { label, command: { type: "generate", source_id: row.id, ...edited } };
  }
  if (job.silent) return { label: "Re-separate", disabledReason: "No original audio to separate." };
  const original = row.origin === "separated" ? row.id : row.pairOf;
  if (!original) {
    return { label: "Re-separate", disabledReason: "This track was generated and has no original to separate." };
  }
  if (pendingSpans) {
    return { label: "Regenerate with new spans", command: { type: "reseparate", source_id: original, ...edited, spans: pendingSpans } };
  }
  return { label: "Re-separate", command: { type: "reseparate", source_id: original, ...edited } };
}

// Pitch is applied by the server's render, so a change is always followed by one.
export function pitchCommands(sourceId: string, semitones: number): Command[] {
  return [
    { type: "set_pitch", source_id: sourceId, semitones: Math.min(12, Math.max(-12, semitones)) },
    { type: "render", include_residual_stem: false },
  ];
}

// Why a change cannot be made right now, or null. One change at a time.
export function regenerateBlockedReason(job: Job, busy: string | null): string | null {
  if (job.state === "new") return "Choose Separate or Generate first.";
  if (job.state === "failed") return "The job failed; upload the video again.";
  return busy !== null || job.state === "running" ? "Another change is still running." : null;
}

// What the engine loads. The URL carries what the audio is made of, so a changed track is fetched again.
// `reload` changes after a command that rewrites stems or the residual under the same file name.
export function engineTracks(job: Job, view: JobView, reload = 0): EngineTrack[] {
  const url = (path: string, key: string) => `${fileUrl(job.id, path)}?v=${encodeURIComponent(key)}`;
  const tracks = view.rows.map((row): EngineTrack => {
    if (row.status !== "done" || !row.trackPath) return { id: row.id, url: null };
    // A pitched copy exists only after a render.
    const pitched = row.pitch !== 0 && job.outputs ? `out/pitch_${row.id}.wav` : null;
    const path = pitched ?? row.trackPath;
    return { id: row.id, url: url(path, `${path}|${row.attempts}|${row.status}|${row.pitch}|${pitched ? job.version : ""}|${reload}`) };
  });
  if (view.residual) {
    // The residual is recomputed when any source is separated again.
    tracks.push({ id: "residual", url: url(view.residual.path, `${view.residual.path}|${job.sources.map((s) => s.attempts).join(",")}|${reload}`) });
  }
  return tracks;
}

// While a change runs the engine keeps what it has loaded, because a pitched copy is written only by the render that ends the change.
export function heldTracks(loaded: EngineTrack[] | null, next: EngineTrack[], busy: string | null): EngineTrack[] {
  return busy !== null && loaded !== null ? loaded : next;
}

// Re-separating or regenerating also renders, so the pitched copies and the export match the new audio.
export function withRender(commands: Command[]): Command[] {
  const heavy = commands.some((c) => c.type === "reseparate" || c.type === "generate");
  return heavy && !commands.some((c) => c.type === "render") ? [...commands, { type: "render", include_residual_stem: false }] : commands;
}
