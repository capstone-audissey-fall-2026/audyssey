import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { job, source, ssr } from "./helpers.mjs";

const step = (key, status, over = {}) => ({ key, status, round: 0, max_rounds: 0, message: "", ...over });
const lanes = [
  { id: "app", name: "App server", models: ["ffmpeg"], steps: ["preprocess", "residual", "render"], up: true },
  { id: "tool:sep:8700", name: "Tool server (sep:8700)", models: ["sam-audio-large-tv"], steps: ["separate"], up: false },
  { id: "tool:gen:8700", name: "Tool server (gen:8700)", models: ["internal-model"], steps: ["generate", "score"], up: null },
];

test("nodeState reports the status and a short count or round", async (context) => {
  const { nodeState } = await (await ssr(context)).ssrLoadModule("/src/lib/board.ts");
  const sources = [source("s1"), source("s2"), source("s3"), source("s4")];
  const plan2 = job({ state: "running", steps: [step("plan", "running", { round: 2, max_rounds: 3 })] });
  assert.deepEqual(nodeState(plan2, "plan"), { status: "running", sub: "Round 2" });
  assert.deepEqual(nodeState(plan2, "validate_plan"), { status: "pending", sub: "" });
  const sep = job({ state: "running", sources, steps: [step("separate:s1", "done"), step("separate:s2", "done"), step("separate:s3", "running")] });
  assert.deepEqual(nodeState(sep, "separate"), { status: "running", sub: "2/4" });
  const failed = job({ steps: [step("separate:s1", "done"), step("separate:s2", "failed")], sources });
  assert.equal(nodeState(failed, "separate").status, "failed");
  assert.deepEqual(nodeState(null, "plan"), { status: "pending", sub: "" });
  assert.equal(nodeState(job({ steps: [step("render", "done")] }), "render").status, "done");
});

test("boardLayout puts each step on the lane of its server; the path not taken is idle", async (context) => {
  const { boardLayout } = await (await ssr(context)).ssrLoadModule("/src/lib/board.ts");
  const separated = job({ method: "separate", sources: [source("s1")] });
  const layout = boardLayout(lanes, separated);
  const node = (step) => layout.nodes.find((n) => n.step === step);
  assert.deepEqual(layout.lanes.map((l) => l.id), ["app", "tool:sep:8700", "tool:gen:8700"]);
  assert.ok(node("separate").y > node("preprocess").y);
  assert.ok(node("generate").y > node("separate").y);
  assert.equal(node("separate").x, node("generate").x); // same column
  assert.ok(node("plan").x > node("preprocess").x);
  assert.equal(node("generate").idle, true);
  assert.equal(node("score").idle, true);
  assert.equal(node("separate").idle, false);
  assert.equal(node("separate").model, "SAM Audio");

  const generated = boardLayout(lanes, job({ method: "generate", sources: [source("s1", { origin: "generated" })] }));
  const gnode = (step) => generated.nodes.find((n) => n.step === step);
  assert.equal(gnode("generate").idle, false);
  assert.equal(gnode("separate").idle, true);
  assert.equal(gnode("judge").idle, true);
  assert.equal(gnode("residual").idle, true);
  // Before a start both paths are possible.
  const fresh = boardLayout(lanes, job({ state: "new", method: null }));
  assert.ok(fresh.nodes.every((n) => !n.idle));
  assert.equal(boardLayout([], null).nodes.length, 9); // the default lanes
  assert.equal(layout.lanes[1].up, false);
});

test("edges carry video, audio and text; a retry loop shows only while it runs", async (context) => {
  const { boardLayout } = await (await ssr(context)).ssrLoadModule("/src/lib/board.ts");
  const keys = (j) => boardLayout(lanes, j).edges.map((e) => e.key);
  const calm = job({ steps: [step("plan", "done"), step("validate_plan", "done")] });
  assert.ok(keys(calm).includes("edge:preprocess>plan"));
  assert.ok(!keys(calm).includes("edge:validate_plan>plan"));
  const retry = job({ state: "running", steps: [step("plan", "running", { round: 2 }), step("validate_plan", "done")] });
  const loop = boardLayout(lanes, retry).edges.find((e) => e.key === "edge:validate_plan>plan");
  assert.ok(loop && loop.loop && loop.state === "active");
  const kinds = new Set(boardLayout(lanes, calm).edges.map((e) => e.kind));
  assert.deepEqual([...kinds].sort(), ["audio", "text", "video"]);
  const edge = boardLayout(lanes, calm).edges[0];
  assert.match(edge.d, /^M /);
});

test("PipelineBoard draws the steps as buttons and opens while the job runs", async (context) => {
  const { default: PipelineBoard } = await (await ssr(context)).ssrLoadModule("/src/components/PipelineBoard.tsx");
  const props = { lanes, step: null, edge: null, onStep() {}, onEdge() {} };
  const running = renderToStaticMarkup(createElement(PipelineBoard, { ...props, job: job({ state: "running", steps: [step("plan", "running")] }) }));
  assert.match(running, /<svg[^>]*class="flow"|<svg[^>]*id="board"/);
  assert.match(running, /role="button"[^>]*aria-label="Plan, [^"]*Running"/);
  assert.match(running, /aria-expanded="true"/);
  assert.match(running, /Pipeline/);
  const ready = renderToStaticMarkup(createElement(PipelineBoard, { ...props, job: job({ state: "ready", steps: [step("plan", "done")] }) }));
  assert.match(ready, /aria-expanded="false"/);
  assert.doesNotMatch(ready, /<svg/);
});
