import type { Job } from "../types";

// One recent-projects row. Jobs have no name or date yet, so the id's first characters label it.
export function projectRow(job: Job): { id: string; label: string; detail: string } {
  const tracks = job.sources.filter((s) => s.status !== "skipped").length;
  const parts = [job.state, `${job.duration.toFixed(1)} s`];
  if (job.method) parts.push(job.method);
  parts.push(`${tracks} ${tracks === 1 ? "track" : "tracks"}`);
  return { id: job.id, label: job.id.slice(0, 6), detail: parts.join(" · ") };
}
