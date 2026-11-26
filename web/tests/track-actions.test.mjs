import assert from "node:assert/strict";
import test from "node:test";
import { job, plan, source, ssr } from "./helpers.mjs";

async function load(context) {
  const server = await ssr(context);
  return [await server.ssrLoadModule("/src/lib/trackActions.ts"), (await server.ssrLoadModule("/src/lib/adapter.ts")).jobToView];
}
const spans = [{ start: 1, end: 2 }];

test("primaryAction picks the label and command for the chosen method", async (context) => {
  const [{ primaryAction }, jobToView] = await load(context);
  const j = job({
    sources: [
      source("s1", { plan: plan("dog") }),
      source("s2", { plan: plan("dog (generated)"), origin: "generated", replaces: "s1" }),
      source("s3", { plan: plan("voice", [{ start: 0, end: 1 }], "dialogue") }),
    ],
  });
  const [dog, gen, voice] = jobToView(j).rows;

  assert.deepEqual(primaryAction(dog, "separate", null, j), { label: "Re-separate", command: { type: "reseparate", source_id: "s1" } });
  assert.deepEqual(primaryAction(dog, "separate", spans, j), {
    label: "Regenerate with new spans",
    command: { type: "reseparate", source_id: "s1", spans },
  });
  assert.deepEqual(primaryAction(dog, "generate", null, j), { label: "Generate instead", command: { type: "generate", source_id: "s1" } });
  // The generated side of a pair regenerates in place, or re-separates the original.
  assert.deepEqual(primaryAction(gen, "generate", null, j), { label: "Regenerate", command: { type: "generate", source_id: "s2" } });
  assert.deepEqual(primaryAction(gen, "separate", null, j), { label: "Re-separate", command: { type: "reseparate", source_id: "s1" } });
  assert.deepEqual(primaryAction(voice, "generate", null, j), { label: "Generate instead", disabledReason: "Speech is not generated." });
  assert.equal(primaryAction(voice, "separate", null, j).command.type, "reseparate");
});

test("primaryAction sends an edited description and refuses what the server would", async (context) => {
  const [{ primaryAction }, jobToView] = await load(context);
  const j = job({ sources: [source("s1", { plan: plan("dog") })] });
  const [dog] = jobToView(j).rows;
  assert.deepEqual(primaryAction(dog, "generate", null, j, "dog barking twice").command, { type: "generate", source_id: "s1", description: "dog barking twice" });
  // Unchanged or blank: not sent.
  assert.equal("description" in primaryAction(dog, "generate", null, j, dog.description).command, false);
  assert.equal("description" in primaryAction(dog, "generate", null, j, "   ").command, false);

  const silent = job({ silent: true, sources: [source("s1", { origin: "generated" })] });
  const [row] = jobToView(silent).rows;
  assert.deepEqual(primaryAction(row, "separate", null, silent), { label: "Re-separate", disabledReason: "No original audio to separate." });
  const lone = job({ sources: [source("s1", { origin: "generated" })] });
  assert.match(primaryAction(jobToView(lone).rows[0], "separate", null, lone).disabledReason, /no original/i);
});

test("withRender adds a render after re-separating or regenerating, once", async (context) => {
  const [{ withRender }] = await load(context);
  const render = { type: "render", include_residual_stem: false };
  assert.deepEqual(withRender([{ type: "reseparate", source_id: "s1" }]), [{ type: "reseparate", source_id: "s1" }, render]);
  assert.deepEqual(withRender([{ type: "generate", source_id: "s1" }, render]), [{ type: "generate", source_id: "s1" }, render]);
  assert.deepEqual(withRender([{ type: "set_gain", source_id: "s1", gain: 1 }]), [{ type: "set_gain", source_id: "s1", gain: 1 }]);
});

test("pitchCommands sets the pitch then renders; engineTracks keys audio by what it plays", async (context) => {
  const [{ pitchCommands, engineTracks }, jobToView] = await load(context);
  assert.deepEqual(pitchCommands("s1", 3), [
    { type: "set_pitch", source_id: "s1", semitones: 3 },
    { type: "render", include_residual_stem: false },
  ]);
  const j = job({
    version: 4,
    sources: [
      source("s1", { attempts: 2 }),
      source("s2", { pitch_semitones: 2 }),
      source("s3", { status: "failed", track_path: null }),
    ],
  });
  const plain = engineTracks(j, jobToView(j));
  assert.deepEqual(plain.map((t) => t.id), ["s1", "s2", "s3", "residual"]);
  assert.equal(plain[0].url, "/api/jobs/abc123def/files/tracks/s1.wav?v=tracks%2Fs1.wav%7C2%7Cdone%7C0%7C%7C0");
  assert.equal(plain[1].url.includes("tracks/s2.wav"), true); // no render yet: the unpitched stem
  assert.equal(plain[2].url, null);
  const rendered = job({ ...j, outputs: { mix_wav: "out/mix.wav", video_mp4: "out/video.mp4", stems: [] } });
  assert.match(engineTracks(rendered, jobToView(rendered))[1].url, /files\/out\/pitch_s2\.wav\?v=/);
  const noResidual = job({ ...j, residual: { path: null, keep: true, gain: 1 } });
  assert.deepEqual(engineTracks(noResidual, jobToView(noResidual)).map((t) => t.id), ["s1", "s2", "s3"]);
});

test("engineTracks urls change when the reload counter does, even if the file name does not", async (context) => {
  const [{ engineTracks }, jobToView] = await load(context);
  const j = job({ sources: [source("s1"), source("s2")] });
  const view = jobToView(j);
  const a = engineTracks(j, view, 0);
  const b = engineTracks(j, view, 1);
  assert.deepEqual(a, engineTracks(j, view));
  assert.equal(a.length, 3);
  a.forEach((t, i) => assert.notEqual(t.url, b[i].url, t.id));
});
