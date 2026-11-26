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
  // Steps that share a spot (everything on one server) are drawn idle first, so the live one is on top.
  const idleFlags = layout.nodes.map((n) => n.idle);
  assert.deepEqual(idleFlags, [...idleFlags].sort((a, b) => Number(b) - Number(a)));
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

test("modelText shortens the model only when a count shares the line; nodes are 108 wide", async (context) => {
  const { boardLayout, modelText } = await (await ssr(context)).ssrLoadModule("/src/lib/board.ts");
  const short = modelText("sam-audio-large-tv", "4/4");
  assert.equal(short.length, 12);
  assert.ok(short.endsWith("…"));
  assert.equal(modelText("ffmpeg", "Round 2"), "ffmpeg");
  assert.equal(modelText("sam-audio-large-tv", ""), "sam-audio-large-tv");
  assert.equal(boardLayout(lanes, null).nodeW, 108);
});

test("PipelineBoard draws the steps as buttons and opens while the job runs", async (context) => {
  const { default: PipelineBoard } = await (await ssr(context)).ssrLoadModule("/src/components/PipelineBoard.tsx");
  const props = { lanes, step: null, edge: null, onStep() {}, onEdge() {} };
  const running = renderToStaticMarkup(createElement(PipelineBoard, { ...props, job: job({ state: "running", steps: [step("plan", "running")] }) }));
  assert.match(running, /<svg[^>]*class="flow"|<svg[^>]*id="board"/);
  assert.match(running, /role="button"[^>]*aria-label="Plan, [^"]*Running"/);
  assert.match(running, /aria-expanded="true"/);
  const round2 = renderToStaticMarkup(createElement(PipelineBoard, { ...props, job: job({ state: "running", steps: [step("plan", "running", { round: 2, max_rounds: 3 })] }) }));
  const plan = (await (await ssr(context)).ssrLoadModule("/src/lib/board.ts")).boardLayout(lanes, null).nodes.find((n) => n.step === "plan");
  assert.match(round2, new RegExp(`<text class="count" text-anchor="end" x="${plan.x + 108 - 10}" y="${plan.y + 35}">Round 2</text>`));
  assert.match(running, /Pipeline/);
  const ready = renderToStaticMarkup(createElement(PipelineBoard, { ...props, job: job({ state: "ready", steps: [step("plan", "done")] }) }));
  assert.match(ready, /aria-expanded="false"/);
  assert.doesNotMatch(ready, /<svg/);
});

test("steps sharing a column on one lane stack on a second row; lanes below shift down", async (context) => {
  const { boardLayout } = await (await ssr(context)).ssrLoadModule("/src/lib/board.ts");
  const all = ["preprocess", "plan", "validate_plan", "separate", "generate", "judge", "score", "residual", "render"];
  const layout = boardLayout([{ id: "all", name: "App server", models: [], steps: all, up: true }], job({ method: null }));
  const node = (step) => layout.nodes.find((n) => n.step === step);
  for (const [first, later] of [["separate", "generate"], ["judge", "score"]]) {
    assert.equal(node(later).x, node(first).x);
    assert.ok(node(later).y > node(first).y);
  }
  assert.equal(new Set(layout.nodes.map((n) => `${n.x},${n.y}`)).size, layout.nodes.length);
  assert.equal(layout.height, 2 * layout.laneH);
  assert.equal(layout.lanes[0].h, 2 * layout.laneH);
  assert.ok(layout.edges.every((e) => !e.d.includes("NaN")));
  // A lane below the collision shifts down by the extra row.
  const below = boardLayout(
    [{ id: "a", name: "A", models: [], steps: all.slice(1), up: true }, { id: "b", name: "B", models: [], steps: ["preprocess"], up: true }],
    job({ method: null }),
  );
  assert.equal(below.lanes[1].y, 2 * below.laneH);
  assert.equal(below.height, 3 * below.laneH);
});
