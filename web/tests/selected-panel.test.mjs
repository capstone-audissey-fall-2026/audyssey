import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { job, plan, source, ssr } from "./helpers.mjs";

async function render(context, sources, id, over = {}) {
  const server = await ssr(context);
  const { default: Panel } = await server.ssrLoadModule("/src/components/SelectedTrackPanel.tsx");
  const { jobToView } = await server.ssrLoadModule("/src/lib/adapter.ts");
  const j = job({ sources, ...(over.job ?? {}) });
  const row = jobToView(j).rows.find((r) => r.id === id);
  const props = { row, job: j, pendingSpans: null, disabled: null, error: null, hasUnsavedEdits: false, onDiscardEdits() {}, onAction() {}, ...over.props };
  return renderToStaticMarkup(createElement(Panel, props));
}

test("a done separated track shows its origin, attempt, judge result and actions", async (context) => {
  const filter = { passed: true, scores: { match: 0.82, clean: 0.7 }, reason: "sounds like a dog", suggestion: null };
  const html = await render(context, [source("s1", { plan: plan("dog"), attempts: 2, filter, pitch_semitones: 1 })], "s1");
  assert.match(html, /aria-label="Selected track"/);
  assert.match(html, />dog</);
  assert.match(html, /Separated/);
  assert.match(html, /Attempt 2/);
  assert.match(html, /sounds like a dog/);
  assert.match(html, /match 0\.82/);
  assert.match(html, /<button[^>]*>Re-separate</);
  assert.match(html, /Separate \(SAM Audio\)/);
  assert.match(html, /Generate \(internal model\)/);
  assert.match(html, /dog sound<\/textarea>/);
  assert.match(html, /\+1 st/);
  assert.match(html, /aria-label="Lower pitch"/);
  assert.match(html, /aria-label="Raise pitch"/);
});

test("pending spans change the primary button; a failed source shows its message and nothing about kept audio", async (context) => {
  const withSpans = await render(context, [source("s1")], "s1", { props: { pendingSpans: [{ start: 1, end: 2 }], hasUnsavedEdits: true } });
  assert.match(withSpans, /Regenerate with new spans/);
  assert.match(withSpans, />Discard edits</);

  const steps = [{ key: "separate:s1", status: "failed", round: 0, max_rounds: 0, message: "Audyssey tools server unreachable at http://x: refused" }];
  const failed = await render(context, [source("s1", { status: "failed", track_path: null })], "s1", { job: { steps } });
  assert.match(failed, /Failed/);
  assert.match(failed, /Audyssey tools server unreachable\./);
  assert.doesNotMatch(failed, /Previous audio kept/);
  assert.doesNotMatch(failed, /pitch/i); // nothing to pitch without audio
});

test("a generated track regenerates in place; unavailable actions say why", async (context) => {
  const generated = await render(context, [source("s1", { origin: "generated" })], "s1");
  assert.match(generated, /<button[^>]*>Regenerate</);
  assert.match(generated, /Generated/);

  const voice = await render(context, [source("s1", { plan: plan("voice", [{ start: 0, end: 1 }], "dialogue") })], "s1", { props: { initialMethod: "generate" } });
  assert.match(voice, /<button[^>]*disabled=""[^>]*aria-describedby="[^"]+"[^>]*>Generate instead</);
  assert.match(voice, /Speech is not generated\./);

  const busy = await render(context, [source("s1")], "s1", { props: { disabled: "Another change is still running." } });
  assert.match(busy, /<button[^>]*disabled=""[^>]*>Re-separate</);
  assert.match(busy, /Another change is still running\./);
  assert.match(busy, /aria-label="Raise pitch"[^>]*disabled=""|disabled=""[^>]*aria-label="Raise pitch"/);
});
