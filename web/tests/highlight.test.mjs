import assert from "node:assert/strict";
import test from "node:test";
import { job, plan, source, ssr } from "./helpers.mjs";

const hint = (time, box = [0.1, 0.2, 0.5, 0.6]) => ({ time, box, description: "dog" });
const withHint = (id, h, over = {}) => source(id, { plan: { ...plan(`source ${id}`), visual_hint: h }, ...over });

async function load(context) {
  const server = await ssr(context);
  return [await server.ssrLoadModule("/src/lib/highlight.ts"), await server.ssrLoadModule("/src/lib/adapter.ts")];
}

test("a box is visible only within 0.5 s of its hint time", async (context) => {
  const [{ visibleBoxes }, { jobToView }] = await load(context);
  const j = job({ sources: [withHint("s1", hint(2))] });
  const { rows } = jobToView(j);
  const at = (t) => visibleBoxes(rows, j.sources, "s1", t).length;
  assert.equal(at(2), 1);
  assert.equal(at(1.5), 1);
  assert.equal(at(2.5), 1);
  assert.equal(at(1.49), 0);
  assert.equal(at(2.51), 0);
  const [box] = visibleBoxes(rows, j.sources, "s1", 2);
  assert.deepEqual(box, { id: "s1", box: [0.1, 0.2, 0.5, 0.6], color: rows[0].color });
});

test("only the selected source is drawn, or every source when nothing is selected", async (context) => {
  const [{ visibleBoxes }, { jobToView }] = await load(context);
  const j = job({ sources: [withHint("s1", hint(1)), withHint("s2", hint(1)), source("s3"), withHint("s4", hint(1), { status: "skipped" })] });
  const { rows } = jobToView(j);
  assert.deepEqual(visibleBoxes(rows, j.sources, "s2", 1).map((b) => b.id), ["s2"]);
  assert.deepEqual(visibleBoxes(rows, j.sources, null, 1).map((b) => b.id), ["s1", "s2"]);
  assert.deepEqual(visibleBoxes(rows, j.sources, "s3", 1), []);
  assert.deepEqual(visibleBoxes(rows, j.sources, null, 9), []);
});

test("the chip names the source, or says it has no on-screen location", async (context) => {
  const [{ highlightChip }, { jobToView }] = await load(context);
  const j = job({ sources: [withHint("s1", hint(1)), source("s2", { plan: plan("rain") })] });
  const { rows } = jobToView(j);
  assert.equal(highlightChip(rows[0], j.sources[0]), "Highlighting source s1");
  assert.equal(highlightChip(rows[1], j.sources[1]), "rain has no on-screen location");
});

test("contentRect fits the picture inside the box", async (context) => {
  const [{ contentRect }] = await load(context);
  assert.deepEqual(contentRect(1600, 900, 1600, 900), { x: 0, y: 0, w: 1, h: 1 });
  // 4:3 picture in a 16:9 box: pillarboxed.
  const r = contentRect(1600, 900, 640, 480);
  assert.ok(Math.abs(r.w - 0.75) < 1e-9 && Math.abs(r.x - 0.125) < 1e-9 && r.y === 0 && r.h === 1);
  // 9:16 picture: pillarboxed a lot.
  const tall = contentRect(1600, 900, 720, 1280);
  assert.ok(Math.abs(tall.w - (900 * (720 / 1280)) / 1600) < 1e-9);
  // Unknown video size: the whole box.
  assert.deepEqual(contentRect(1600, 900, 0, 0), { x: 0, y: 0, w: 1, h: 1 });
});
