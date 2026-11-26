import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { job, plan, source, ssr } from "./helpers.mjs";
import { render, timelineProps } from "./timeline-helpers.mjs";

async function load(context) {
  const server = await ssr(context);
  return [await server.ssrLoadModule("/src/components/Timeline.tsx"), (await server.ssrLoadModule("/src/lib/adapter.ts")).jobToView, await server.ssrLoadModule("/src/lib/trackActions.ts")];
}

test("volume slider is 0..200 %, with Play and Solo next to it", async (context) => {
  const [{ default: Timeline }, jobToView] = await load(context);
  const view = jobToView(job({ sources: [source("s1", { plan: plan("Door"), gain: 1.35 })] }));
  const html = render(Timeline, timelineProps(view));
  const slider = html.match(/<input[^>]*aria-label="Door volume"[^>]*>/)?.[0] ?? "";
  assert.match(slider, /max="200"/);
  assert.match(slider, /min="0"/);
  assert.match(slider, /step="5"/);
  assert.match(slider, /type="range"/);
  assert.match(slider, /value="135"/);
  assert.doesNotMatch(slider, /disabled/);
  assert.match(html, /<output>135%<\/output>/);
  assert.match(html, /aria-label="Play Door"/);
  assert.match(html, /aria-label="Solo Door"/);
});

test("double-click on the volume slider restores 100 % and commits it", async (context) => {
  const [{ GainSlider }] = await load(context);
  const calls = [];
  const input = (percent) =>
    GainSlider({ label: "Door", percent, disabled: false, onChange: (p) => calls.push(["change", p]), onCommit: (p) => calls.push(["commit", p]) }).props.children[0];
  input(135).props.onDoubleClick();
  assert.deepEqual(calls, [["change", 100], ["commit", 100]]);
  calls.length = 0;
  input(100).props.onDoubleClick(); // already 100 %: nothing to send
  assert.deepEqual(calls, []);
  // Releasing the slider (pointer or keyboard) commits the value once.
  input(80).props.onPointerUp({ currentTarget: { value: "140" } });
  input(80).props.onKeyUp({ currentTarget: { value: "90" } });
  assert.deepEqual(calls, [["commit", 140], ["commit", 90]]);
});

test("keep on one side of a pair drops the other; the residual has no pair", async (context) => {
  const [, jobToView, { keepCommands }] = await load(context);
  const view = jobToView(
    job({
      sources: [
        source("s1", { keep: false }),
        source("s2", { origin: "generated", replaces: "s1", keep: true }),
        source("s3"),
      ],
    }),
  );
  assert.deepEqual(keepCommands(view, "s1", true), [{ type: "keep", source_id: "s1" }, { type: "drop", source_id: "s2" }]);
  assert.deepEqual(keepCommands(view, "s2", false), [{ type: "drop", source_id: "s2" }]);
  // The other side is already off: nothing extra to send.
  assert.deepEqual(keepCommands(view, "s2", true), [{ type: "keep", source_id: "s2" }]);
  assert.deepEqual(keepCommands(view, "s3", true), [{ type: "keep", source_id: "s3" }]);
  assert.deepEqual(keepCommands(view, "residual", true), [{ type: "keep", source_id: "residual" }]);
});

test("the keep switch reflects the source and span lanes list their boxes", async (context) => {
  const [{ default: Timeline }, jobToView] = await load(context);
  const view = jobToView(job({ duration: 10, sources: [source("s1", { plan: plan("dog"), keep: false })] }));
  const html = render(Timeline, timelineProps(view));
  const tag = html.match(/<button[^>]*aria-label="Include dog in the mix"[^>]*>/)?.[0] ?? "";
  assert.match(tag, /role="switch"/);
  assert.match(tag, /aria-checked="false"/);
  // A pending span draft is what the lane draws.
  const withDraft = render(Timeline, timelineProps(view, { pending: { get: (id) => (id === "s1" ? [{ start: 5, end: 6 }] : null) } }));
  assert.match(withDraft, /left:50%;width:10%/);
});
