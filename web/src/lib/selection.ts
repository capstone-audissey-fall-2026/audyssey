import type { SourceStatus } from "../types";

// The first two follow the approved mockup (--c-player, --c-enemy); the rest are vivid and distinct on video.
const OBJECT_COLORS = ["#4cc9f0", "#ff7ab6", "#ffd166", "#9be564", "#ff8c42", "#b388ff", "#ff4d4d", "#2ec4b6"];
export const NONE_COLOR = "#9aa3b2";

// Rows cycle through the palette (never gray); a negative index means "no colour".
export function objectColor(index: number): string {
  return index < 0 ? NONE_COLOR : OBJECT_COLORS[index % OBJECT_COLORS.length];
}

export function statusView(
  row: { status: SourceStatus; origin: "separated" | "generated" },
  appRunning: boolean,
): { label: "Done" | "Separating…" | "Generating…" | "Queued" | "Failed" | null; tone: "ok" | "run" | "wait" | "err" | null } {
  if (row.status === "done") return { label: "Done", tone: "ok" };
  if (row.status === "running") return { label: row.origin === "generated" ? "Generating…" : "Separating…", tone: "run" };
  if (row.status === "failed") return { label: "Failed", tone: "err" };
  return appRunning ? { label: "Queued", tone: "wait" } : { label: null, tone: null };
}

export type TransportAction = "stop-preview" | "pause-video" | "play-solo" | "play-mix";

// Main play button: a running preview stem or video always stops first; only an idle press starts playback.
export function transportAction(s: {
  previewPlaying: boolean;
  videoPlaying: boolean;
  soloTrackId: string | null;
}): TransportAction {
  if (s.previewPlaying) return "stop-preview";
  if (s.videoPlaying) return "pause-video";
  return s.soloTrackId ? "play-solo" : "play-mix";
}

// Solo toggled while something plays: restart with the new choice, else leave playback alone.
// Solo on -> that stem; Solo off -> the mix, but only if a stem preview was playing (the mix already plays otherwise).
export function soloToggleAction(s: {
  previewPlaying: boolean;
  videoPlaying: boolean;
  soloTrackId: string | null;
}): "play-solo" | "play-mix" | null {
  if (!s.previewPlaying && !s.videoPlaying) return null;
  if (s.soloTrackId) return "play-solo";
  return s.previewPlaying ? "play-mix" : null;
}

// Keeps the selection while its track exists; otherwise (first load, new job) the first track.
export function reconcileSelection(current: string | null, trackIds: string[]): string | null {
  if (trackIds.length === 0 || (current !== null && trackIds.includes(current))) return current;
  return trackIds[0];
}
