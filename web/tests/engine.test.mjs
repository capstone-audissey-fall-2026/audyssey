import assert from "node:assert/strict";
import test from "node:test";
import { ssr } from "./helpers.mjs";

// A tiny stand-in for AudioContext: records what the engine starts and stops.
function fakeContext() {
  const ctx = {
    currentTime: 0,
    destination: {},
    sources: [],
    gains: [],
    resume: async () => {},
    createGain() {
      const node = { gain: { value: 1 }, connected: true, connect() {}, disconnect() { node.connected = false; } };
      ctx.gains.push(node);
      return node;
    },
    createBufferSource() {
      const src = {
        buffer: null,
        started: null,
        stopped: false,
        connect() {},
        start(when, offset) { src.started = { when, offset }; },
        stop() { src.stopped = true; },
      };
      ctx.sources.push(src);
      return src;
    },
    decodeAudioData: async (bytes) => ({ duration: bytes.byteLength / 10, getChannelData: () => new Float32Array(4) }),
  };
  return ctx;
}
const fakeVideo = () => ({ muted: false, currentTime: 0, duration: 20, play: async () => {}, pause() {} });
const answer = (sizes) => async (url) => ({ arrayBuffer: async () => new ArrayBuffer(sizes[url] ?? 100) });

async function engineWith(context, tracks) {
  const server = await ssr(context);
  const { AudioEngine, effectiveGain } = await server.ssrLoadModule("/src/lib/audioEngine.ts");
  const real = globalThis.fetch;
  context.after(() => (globalThis.fetch = real));
  globalThis.fetch = answer({ "/a.wav": 100, "/b.wav": 50 });
  const ctx = fakeContext();
  const engine = new AudioEngine(fakeVideo(), ctx);
  engine.duration = 20;
  context.after(() => engine.dispose());
  if (tracks) await engine.setTracks(tracks);
  return { engine, ctx, effectiveGain };
}

test("effectiveGain: dropped and non-solo tracks are silent", async (context) => {
  const { effectiveGain } = await engineWith(context);
  assert.equal(effectiveGain({ gain: 1.5, keep: false }, null, "a"), 0);
  assert.equal(effectiveGain({ gain: 1.5, keep: true }, "b", "a"), 0);
  assert.equal(effectiveGain({ gain: 1.5, keep: true }, "a", "a"), 1.5);
  assert.equal(effectiveGain({ gain: 1.5, keep: true }, null, "a"), 1.5);
});

test("seek while playing restarts the sources at the new offset", async (context) => {
  const { engine, ctx } = await engineWith(context, [{ id: "a", url: "/a.wav" }, { id: "b", url: "/b.wav" }]);
  engine.play();
  assert.deepEqual(ctx.sources.map((s) => s.started.offset), [0, 0]);
  ctx.currentTime = 1;
  engine.seek(3);
  assert.ok(ctx.sources.slice(0, 2).every((s) => s.stopped));
  // b is 5 s long, a is 10 s: both reach 3 s.
  assert.deepEqual(ctx.sources.slice(2).map((s) => s.started.offset), [3, 3]);
  ctx.currentTime = 3;
  assert.equal(engine.now(), 5);
  engine.seek(7); // past the end of b
  assert.equal(ctx.sources.slice(4).length, 1);
  engine.pause();
  assert.ok(ctx.sources.every((s) => s.stopped));
});

test("dispose stops every source and releases the gain nodes", async (context) => {
  const { engine, ctx } = await engineWith(context, [{ id: "a", url: "/a.wav" }, { id: "b", url: "/b.wav" }]);
  engine.play();
  engine.dispose();
  assert.ok(ctx.sources.length === 2 && ctx.sources.every((s) => s.stopped));
  assert.ok(ctx.gains.every((g) => !g.connected)); // tracks and master
});

test("a track without a url has no audio, so nothing stale plays", async (context) => {
  const { engine, ctx } = await engineWith(context, [{ id: "a", url: "/a.wav" }]);
  await engine.setTracks([{ id: "a", url: null }]);
  engine.play();
  assert.equal(ctx.sources.length, 0);
  assert.equal(engine.peaks("a", 4), null);
});

test("setTracks releases tracks that are no longer listed", async (context) => {
  const { engine, ctx } = await engineWith(context, [{ id: "a", url: "/a.wav" }]);
  await engine.setTracks([]);
  assert.deepEqual(ctx.gains.map((g) => g.connected), [true, false]); // master stays, the track is released
});

test("a slow load for an old url does not replace the newer buffer", async (context) => {
  const { engine, ctx } = await engineWith(context);
  const release = {};
  globalThis.fetch = (url) => new Promise((resolve) => (release[url] = () => resolve({ arrayBuffer: async () => new ArrayBuffer(url === "/a.wav" ? 100 : 50) })));
  const first = engine.setTracks([{ id: "a", url: "/a.wav" }]);
  const second = engine.setTracks([{ id: "a", url: "/b.wav" }]);
  release["/b.wav"]();
  await second;
  release["/a.wav"]();
  await first;
  engine.play();
  assert.equal(ctx.sources[0].buffer.duration, 5);
});

test("solo, keep and gain change the gain nodes without restarting", async (context) => {
  const { engine, ctx } = await engineWith(context, [{ id: "a", url: "/a.wav" }, { id: "b", url: "/b.wav" }]);
  const [ga, gb] = ctx.gains.slice(1); // gains[0] is the master
  engine.setGain("a", 1.5);
  assert.equal(ga.gain.value, 1.5);
  engine.setSolo("b");
  assert.deepEqual([ga.gain.value, gb.gain.value], [0, 1]);
  engine.setSolo(null);
  engine.setKeep("b", false);
  assert.deepEqual([ga.gain.value, gb.gain.value], [1.5, 0]);
});

test("playOnly plays one track, even a dropped one, then returns to the mix", async (context) => {
  const { engine, ctx } = await engineWith(context, [{ id: "a", url: "/a.wav" }, { id: "b", url: "/b.wav" }]);
  const [ga, gb] = ctx.gains.slice(1); // gains[0] is the master
  engine.setKeep("b", false);
  engine.playOnly("b");
  assert.deepEqual([ga.gain.value, gb.gain.value], [0, 1]);
  engine.pause();
  assert.deepEqual([ga.gain.value, gb.gain.value], [1, 0]);
});

test("original mode plays the video's own audio, not the mix", async (context) => {
  const { engine, ctx } = await engineWith(context, [{ id: "a", url: "/a.wav" }]);
  engine.setMode("original");
  engine.play();
  assert.equal(ctx.sources.length, 0);
  assert.equal(engine.video.muted, false);
  engine.setMode("edit");
  assert.equal(ctx.sources.length, 1);
  assert.equal(engine.video.muted, true);
});

test("onTime reports seeks and can be unsubscribed", async (context) => {
  const { engine } = await engineWith(context, []);
  const seen = [];
  const off = engine.onTime((t) => seen.push(t));
  engine.seek(2);
  off();
  engine.seek(4);
  assert.deepEqual(seen, [2]);
});

test("onLoaded fires when a buffer finishes decoding, also for a load started earlier", async (context) => {
  const { engine } = await engineWith(context);
  let loaded = 0;
  engine.onLoaded(() => (loaded += 1));
  let release;
  globalThis.fetch = () => new Promise((resolve) => (release = () => resolve({ arrayBuffer: async () => new ArrayBuffer(100) })));
  const first = engine.setTracks([{ id: "a", url: "/a.wav" }]);
  const second = engine.setTracks([{ id: "a", url: "/a.wav" }, { id: "b", url: null }]); // same url: no second fetch
  release();
  await first;
  await second;
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(loaded, 1);
  assert.ok(engine.peaks("a", 4));
});
