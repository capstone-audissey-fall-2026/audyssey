import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { job, ssr } from "./helpers.mjs";

const form = { name: "  door slam ", kind: "sfx", description: " a heavy door ", method: "separate" };
const spans = [{ start: 1, end: 3 }];

test("newTrackSpan is 2 s from the playhead, kept inside the video", async (context) => {
  const { newTrackSpan } = await (await ssr(context)).ssrLoadModule("/src/lib/newTrack.ts");
  assert.deepEqual(newTrackSpan(1.5, 10), { start: 1.5, end: 3.5 });
  assert.deepEqual(newTrackSpan(9.5, 10), { start: 9.5, end: 10 });
  assert.deepEqual(newTrackSpan(-1, 10), { start: 0, end: 2 });
  assert.deepEqual(newTrackSpan(0, 1), { start: 0, end: 1 });
});

test("newTrackCommand builds add_source and refuses what the server would", async (context) => {
  const { newTrackCommand } = await (await ssr(context)).ssrLoadModule("/src/lib/newTrack.ts");
  assert.deepEqual(newTrackCommand(form, spans, job()), {
    type: "add_source",
    method: "separate",
    plan: { name: "door slam", kind: "sfx", description: "a heavy door", spans, visual_hint: null },
  });
  // A silent video can only generate.
  assert.equal(newTrackCommand(form, spans, job({ silent: true })).method, "generate");
  assert.throws(() => newTrackCommand({ ...form, kind: "dialogue", method: "generate" }, spans, job()), /Speech is not generated\./);
  assert.throws(() => newTrackCommand({ ...form, kind: "dialogue" }, spans, job({ silent: true })), /Speech is not generated\./);
  assert.equal(newTrackCommand({ ...form, kind: "dialogue" }, spans, job()).method, "separate");
});

test("NewTrackPanel lists the spans and explains a silent video", async (context) => {
  const { default: Panel } = await (await ssr(context)).ssrLoadModule("/src/components/NewTrackPanel.tsx");
  const props = { job: job(), spans: [{ start: 1, end: 3 }, { start: 4, end: 4.5 }], disabled: null, onRemoveSpan() {}, onCancel() {}, onCreate: async () => {} };
  const html = renderToStaticMarkup(createElement(Panel, props));
  assert.match(html, /aria-label="New track"/);
  assert.match(html, /1\.0–3\.0 s/);
  assert.match(html, /4\.0–4\.5 s/);
  for (const kind of ["sfx", "ambience", "music", "dialogue"]) assert.match(html, new RegExp(`<option[^>]*value="${kind}"`));
  assert.match(html, /Separate \(SAM Audio\)/);
  assert.match(html, /Generate \(internal model\)/);
  assert.match(html, /<button[^>]*type="submit"[^>]*disabled/); // empty name and description

  const silent = renderToStaticMarkup(createElement(Panel, { ...props, job: job({ silent: true }) }));
  assert.match(silent, /<option[^>]*value="separate"[^>]*disabled/);
  assert.match(silent, /No original audio to separate\./);
  const blocked = renderToStaticMarkup(createElement(Panel, { ...props, disabled: "Another change is still running." }));
  assert.match(blocked, /Another change is still running\./);
});
