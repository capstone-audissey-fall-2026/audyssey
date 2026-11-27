import assert from "node:assert/strict";
import test from "node:test";
import { job, plan, source, ssr } from "./helpers.mjs";
import { fakeEngine, laneOf, render, timelineProps } from "./timeline-helpers.mjs";

async function load(context) {
  const server = await ssr(context);
  return [(await server.ssrLoadModule("/src/components/Timeline.tsx")).default, (await server.ssrLoadModule("/src/lib/adapter.ts")).jobToView];
}
const twoSpans = [{ start: 0, end: 1 }, { start: 2, end: 3 }];

test("a generated lane shows its spans read-only, with the reason", async (context) => {
  const [Timeline, jobToView] = await load(context);
  const view = jobToView(
    job({
      sources: [
        source("s1", { plan: plan("dog", twoSpans) }),
        source("s2", { plan: plan("dog (generated)", twoSpans), origin: "generated", replaces: "s1" }),
      ],
    }),
  );
  const html = render(Timeline, timelineProps(view));
  const separated = laneOf(html, "s1");
  const generated = laneOf(html, "s2");
  assert.equal((separated.match(/ev-handle-left/g) ?? []).length, 2);
  assert.doesNotMatch(generated, /ev-handle/);
  assert.match(generated, /title="Spans of generated tracks cannot be edited\."/);
  assert.equal((generated.match(/class="ev"/g) ?? []).length, 2);
});

test("a silent video has no residual lane and read-only spans", async (context) => {
  const [Timeline, jobToView] = await load(context);
  const view = jobToView(
    job({
      silent: true,
      residual: { path: null, keep: true, gain: 1 },
      sources: [source("s1", { origin: "generated", plan: plan("rain", twoSpans) })],
    }),
  );
  const html = render(Timeline, timelineProps(view));
  assert.doesNotMatch(html, /Rest of the original audio/);
  assert.doesNotMatch(html, /ev-handle/);
});

test("a failed source shows Failed, no waveform and a disabled Play", async (context) => {
  const [Timeline, jobToView] = await load(context);
  const steps = [{ key: "separate:s2", status: "failed", round: 0, max_rounds: 0, message: "tools server unreachable" }];
  const view = jobToView(
    job({
      steps,
      sources: [source("s1", { plan: plan("ok one") }), source("s2", { plan: plan("bad one"), status: "failed", track_path: null })],
    }),
  );
  const html = render(Timeline, timelineProps(view, { engine: fakeEngine }));
  const ok = laneOf(html, "s1");
  const bad = laneOf(html, "s2");
  assert.match(ok, /<polygon/);
  assert.doesNotMatch(bad, /<polygon/);
  assert.match(bad, /Failed/);
  assert.match(bad, /tools server unreachable/);
  assert.match(bad, /<button[^>]*aria-label="Play bad one"[^>]*disabled=""|<button[^>]*disabled=""[^>]*aria-label="Play bad one"/);
  assert.doesNotMatch(ok, /aria-label="Play ok one"[^>]*disabled/);
});

test("edits are disabled while a command runs, but listening is not", async (context) => {
  const [Timeline, jobToView] = await load(context);
  const view = jobToView(job({ sources: [source("s1", { plan: plan("dog", twoSpans) })] }));
  const html = render(Timeline, timelineProps(view, { disabled: "Another change is still running." }));
  const tag = (label) => html.match(new RegExp(`<[a-z]+[^>]*aria-label="${label}"[^>]*>`))?.[0] ?? "";
  assert.match(tag("dog volume"), /disabled=""/);
  assert.match(tag("Include dog in the mix"), /disabled=""/);
  assert.doesNotMatch(tag("Play dog"), /disabled/);
  assert.doesNotMatch(tag("Solo dog"), /disabled/);
  assert.doesNotMatch(html, /ev-handle/);
});

test("the playhead and ruler follow the time in seconds", async (context) => {
  const [Timeline, jobToView] = await load(context);
  const view = jobToView(job({ duration: 10, sources: [source("s1")] }));
  assert.match(render(Timeline, timelineProps(view, { time: 2.5 })), /class="playhead" style="left:25%"/);
  assert.match(render(Timeline, timelineProps(view)), /0 s/);
});
