import assert from "node:assert/strict";
import test from "node:test";
import { job, plan, source, ssr } from "./helpers.mjs";

test("jobToView orders pairs, hides skipped sources and builds span ids", async (context) => {
  const { jobToView } = await (await ssr(context)).ssrLoadModule("/src/lib/adapter.ts");
  const view = jobToView(
    job({
      sources: [
        source("s1"),
        source("s2", { plan: plan("dog", [{ start: 0, end: 1 }, { start: 2, end: 3 }]) }),
        source("s3", { status: "skipped" }),
        source("s4", { origin: "generated", replaces: "s1", plan: plan("gen") }),
      ],
    }),
  );
  assert.deepEqual(view.rows.map((r) => r.id), ["s1", "s4", "s2"]);
  assert.equal(view.rows[0].pairOf, "s4");
  assert.equal(view.rows[1].pairOf, "s1");
  assert.equal(view.rows[2].pairOf, null);
  assert.deepEqual(view.skipped.map((s) => s.id), ["s3"]);
  assert.deepEqual(view.rows[2].spans.map((s) => s.id), ["s2#0", "s2#1"]);
  assert.deepEqual(view.rows[2].spans[1], { id: "s2#1", start: 2, end: 3 });
  assert.equal(view.duration, 7.1);
  assert.equal(new Set(view.rows.map((r) => r.color)).size, 3);
});

test("jobToView drops the residual row when there is no residual file", async (context) => {
  const { jobToView } = await (await ssr(context)).ssrLoadModule("/src/lib/adapter.ts");
  assert.equal(jobToView(job({ residual: { path: null, keep: true, gain: 1 } })).residual, null);
  assert.deepEqual(jobToView(job({ residual: { path: "r.wav", keep: false, gain: 0.5 } })).residual, {
    path: "r.wav",
    keep: false,
    gain: 0.5,
  });
});

test("spans are editable only for separated sources of a video with audio", async (context) => {
  const { jobToView } = await (await ssr(context)).ssrLoadModule("/src/lib/adapter.ts");
  const sources = [source("s1"), source("s2", { origin: "generated", replaces: "s1" })];
  const normal = jobToView(job({ sources }));
  assert.deepEqual(normal.rows.map((r) => r.spansEditable), [true, false]);
  const silent = jobToView(job({ silent: true, sources }));
  assert.deepEqual(silent.rows.map((r) => r.spansEditable), [false, false]);
});

test("a failed source keeps its row without a track", async (context) => {
  const { jobToView } = await (await ssr(context)).ssrLoadModule("/src/lib/adapter.ts");
  const [row] = jobToView(job({ sources: [source("s1", { status: "failed", track_path: null, attempts: 2 })] })).rows;
  assert.equal(row.status, "failed");
  assert.equal(row.trackPath, null);
  assert.equal(row.attempts, 2);
  assert.equal(row.origin, "separated");
});
