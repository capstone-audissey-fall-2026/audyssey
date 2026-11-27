import { createServer } from "vite";

// One Vite SSR server per test; closed when the test ends.
export async function ssr(context) {
  const server = await createServer({
    appType: "custom",
    optimizeDeps: { noDiscovery: true },
    server: { middlewareMode: true },
  });
  context.after(() => server.close());
  return server;
}

export const plan = (name, spans = [{ start: 0, end: 1 }], kind = "sfx") => ({
  name,
  kind,
  description: `${name} sound`,
  spans,
  visual_hint: null,
});

export const source = (id, over = {}) => ({
  id,
  plan: plan(over.name ?? `source ${id}`),
  origin: "separated",
  replaces: null,
  track_path: `tracks/${id}.wav`,
  filter: null,
  status: "done",
  attempts: 1,
  keep: true,
  gain: 1,
  pitch_semitones: 0,
  ...over,
});

export const job = (over = {}) => ({
  id: "abc123def",
  video_path: "input.mp4",
  silent: false,
  duration: 7.1,
  audio_path: "audio.wav",
  mono_path: "mono.wav",
  peaks_path: "peaks.json",
  sources: [],
  residual: { path: "residual.wav", keep: true, gain: 1 },
  plan_issues: [],
  steps: [],
  outputs: null,
  state: "ready",
  method: "separate",
  version: 1,
  error: null,
  ...over,
});
