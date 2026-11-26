import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { job, plan, source, ssr } from "./helpers.mjs";

async function load(context) {
  const server = await ssr(context);
  return [await server.ssrLoadModule("/src/components/EditBar.tsx"), await server.ssrLoadModule("/src/lib/editBar.ts"), (await server.ssrLoadModule("/src/lib/adapter.ts")).jobToView];
}
const j = job({ sources: [source("s1", { plan: plan("dog"), gain: 1, pitch_semitones: 2 }), source("s2", { plan: plan("rain") })] });

test("commandSentence says what will change, from the current value", async (context) => {
  const [, { commandSentence }, jobToView] = await load(context);
  const view = jobToView(j);
  assert.equal(commandSentence({ type: "set_gain", source_id: "s1", gain: 0.5 }, view), "dog volume 100% → 50%");
  assert.equal(commandSentence({ type: "set_pitch", source_id: "s1", semitones: 3 }, view), "dog pitch +2 st → +3 st");
  assert.equal(commandSentence({ type: "drop", source_id: "s2" }, view), "Turn off rain");
  assert.equal(commandSentence({ type: "keep", source_id: "s2" }, view), "Turn on rain");
  assert.equal(commandSentence({ type: "reseparate", source_id: "s1" }, view), "Re-separate dog");
  assert.equal(commandSentence({ type: "generate", source_id: "s1" }, view), "Generate dog instead");
  assert.equal(commandSentence({ type: "set_gain", source_id: "residual", gain: 0 }, view), "Rest of the original audio volume 100% → 0%");
  assert.equal(commandSentence({ type: "add_source", method: "generate", plan: plan("wind") }, view), "Add source: wind (generate)");
  assert.equal(commandSentence({ type: "render", include_residual_stem: false }, view), "Mix the result");
});

test("commandsFor adds the render that a pitch change needs", async (context) => {
  const [, { commandsFor }] = await load(context);
  assert.deepEqual(commandsFor({ type: "set_pitch", source_id: "s1", semitones: 3 }), [
    { type: "set_pitch", source_id: "s1", semitones: 3 },
    { type: "render", include_residual_stem: false },
  ]);
  assert.deepEqual(commandsFor({ type: "drop", source_id: "s1" }), [{ type: "drop", source_id: "s1" }]);
});

test("CommandCard offers Run, Edit and Cancel; clarify offers target chips", async (context) => {
  const [{ CommandCard, ClarifyCard }, , jobToView] = await load(context);
  const view = jobToView(j);
  const card = renderToStaticMarkup(createElement(CommandCard, { decision: { type: "set_gain", source_id: "s1", gain: 0.5 }, view, editing: false, onRun() {}, onEdit() {}, onCancel() {} }));
  assert.match(card, /dog volume 100% → 50%/);
  assert.match(card, />Run</);
  assert.match(card, />Edit</);
  assert.match(card, />Cancel</);
  const editing = renderToStaticMarkup(createElement(CommandCard, { decision: { type: "set_gain", source_id: "s1", gain: 0.5 }, view, editing: true, onRun() {}, onEdit() {}, onCancel() {} }));
  assert.match(editing, /<input[^>]*type="number"[^>]*value="50"|<input[^>]*value="50"[^>]*type="number"/);
  assert.match(editing, /max="200"/);
  assert.doesNotMatch(editing, />Edit</);
  // Commands with nothing to edit have no Edit button.
  assert.doesNotMatch(renderToStaticMarkup(createElement(CommandCard, { decision: { type: "drop", source_id: "s2" }, view, editing: false, onRun() {}, onEdit() {}, onCancel() {} })), />Edit</);

  const clarify = renderToStaticMarkup(createElement(ClarifyCard, { decision: { type: "clarify", reason: "ambiguous_target", question: "Which sound?" }, view, onPick() {}, onCancel() {} }));
  assert.match(clarify, /Which sound\?/);
  assert.match(clarify, /class="nlchip"[^>]*>(?:<svg[^>]*>.*?<\/svg>)?dog</);
  assert.match(clarify, />rain</);
  assert.match(clarify, /Rest of the original audio/);
  const other = renderToStaticMarkup(createElement(ClarifyCard, { decision: { type: "clarify", reason: "missing_value", question: "How much?" }, view, onPick() {}, onCancel() {} }));
  assert.doesNotMatch(other, /nlchip/);
});

test("EditBar is off for the stub router and before the job is ready", async (context) => {
  const [{ default: EditBar }, , jobToView] = await load(context);
  const base = { job: j, view: jobToView(j), router: "real", disabled: null, onRun() {}, onTarget() {} };
  const on = renderToStaticMarkup(createElement(EditBar, base));
  assert.doesNotMatch(on, /<input[^>]*disabled/);
  assert.match(on, /Say what to change/);
  const stub = renderToStaticMarkup(createElement(EditBar, { ...base, router: "stub" }));
  assert.match(stub, /<input[^>]*disabled/);
  assert.match(stub, /AUDYSSEY_ROUTER/);
  const busy = renderToStaticMarkup(createElement(EditBar, { ...base, disabled: "Another change is still running." }));
  assert.match(busy, /<input[^>]*disabled/);
});
