import type { Job } from "../types";

export interface StatusLine {
  tone: "idle" | "run" | "done" | "fail";
  text: string;
  progress: number | null; // 0..1, or null for an indeterminate bar
}

const BUSY_TEXT: Record<string, string> = { export: "Exporting…", start: "Starting…", upload: "Uploading…" };

const STEP_TEXT: Record<string, string> = {
  preprocess: "Preparing the video",
  plan: "Planning sounds",
  validate_plan: "Checking the plan",
  ground: "Locating sound sources",
  separate: "Separating",
  generate: "Generating",
  judge: "Checking quality",
  score: "Scoring",
  residual: "Computing the rest of the audio",
  render: "Rendering",
};

// These steps run once per source, so they can say "2 of 3".
const PER_SOURCE = new Set(["separate", "generate", "judge", "score"]);

const stepKey = (key: string) => key.split(":")[0];

export function statusLine(job: Job | null, busy: string | null): StatusLine {
  if (busy) return { tone: "run", text: BUSY_TEXT[busy] ?? "Working…", progress: null };
  if (!job) return { tone: "idle", text: "Open a video to start.", progress: null };
  if (job.state === "new") return { tone: "idle", text: "Choose Separate or Generate to start.", progress: null };
  if (job.state === "failed") return { tone: "fail", text: job.error || "Something went wrong. Try again.", progress: null };
  const tracks = job.sources.filter((s) => s.status !== "skipped").length;
  if (job.state === "ready") {
    if (tracks === 0) return { tone: "done", text: "Done. No sound sources found.", progress: null };
    return { tone: "done", text: `Done. ${tracks} ${tracks === 1 ? "track" : "tracks"} ready to play.`, progress: null };
  }
  const running = job.steps.find((s) => s.status === "running");
  if (!running) return { tone: "run", text: "Working…", progress: null };
  const key = stepKey(running.key);
  const verb = STEP_TEXT[key] ?? "Working";
  if (PER_SOURCE.has(key)) {
    const group = job.steps.filter((s) => stepKey(s.key) === key);
    const done = group.filter((s) => s.status !== "running" && s.status !== "pending").length;
    const total = Math.max(tracks, group.length);
    return { tone: "run", text: `${verb} ${done + 1} of ${total}`, progress: done / total };
  }
  return { tone: "run", text: running.round > 1 ? `${verb} (round ${running.round})` : verb, progress: null };
}
